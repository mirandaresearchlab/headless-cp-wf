#!/usr/bin/env python3
"""ILLUMINATION, SEGMENT and ANALYSIS steps: run one CellProfiler task, then check what it wrote.

illumination (one task per plate)
  In:  the plate manifest (all image sets of the plate) and the illumination pipeline.
  Out: result/illumination/Illum<Channel>.npy and provenance.json (plate and SHA-256 per file).
segmentation (one task per group of batches; only for pipelines with RunCellpose)
  In:  the batch manifests of the group, the segmentation pipeline and the illumination folder.
  Out: result/segmentation/<batch>/masks/*.tiff, mask_manifest.csv and validation.json.
  Runs --workers CellProfiler processes at the same time on parts of the group. On a GPU they
  share the GPU, so it has work while the other workers load images or find the objects.
analysis (one task per batch)
  In:  the batch manifest, the analysis pipeline, the illumination folder of the same plate and,
       with RunCellpose, the segmentation folder of the batch (staged as segmentation/).
  Out: result/analysis/<batch>/features/*.csv.gz, validation.json, and result/masks/*.tiff.
All write result/logs/<batch>.log, <batch>.metrics.json and <batch>.load_data.csv.

What happens inside one analysis task:
  1. Check each .npy file against the checksum in provenance.json of the same plate.
  2. Add the .npy file names to every manifest row. Write load_data.csv.
  3. Run CellProfiler headless on load_data.csv.
  4. realign(): move shifted AreaShape and Texture values back to their objects.
  5. validate_analysis(): check the tables and masks against the manifest. With RunCellpose,
     compare_masks() also checks that the loaded objects are the SEGMENT masks, label for label.
  6. Compress the tables and move the masks next to the batch folder.
"""

import argparse
import csv
import gzip
import hashlib
import json
import os
import resource
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import tifffile

from cp_inputs import read_csv, write_csv

# CellProfiler 4.2.8.1 computes these measurements only for labels that have pixels
# (MeasureObjectSizeShape uses regionprops, MeasureTexture uses numpy.unique), then stores the
# values by position, not by object number. So an object without pixels, such as a cytoplasm
# that its nucleus covers fully, moves the values of every later object one row up.
# Zernike, Feret and all other measurements use the object number and stay correct.
SHIFTED = {
    'AreaShape_' + f
    for f in (
        'Area',
        'Perimeter',
        'MajorAxisLength',
        'MinorAxisLength',
        'Eccentricity',
        'Orientation',
        'Center_X',
        'Center_Y',
        'BoundingBoxArea',
        'BoundingBoxMinimum_X',
        'BoundingBoxMaximum_X',
        'BoundingBoxMinimum_Y',
        'BoundingBoxMaximum_Y',
        'FormFactor',
        'Extent',
        'Solidity',
        'Compactness',
        'EulerNumber',
        'MaximumRadius',
        'MeanRadius',
        'MedianRadius',
        'ConvexArea',
        'EquivalentDiameter',
    )
}
SHIFTED_PREFIXES = (
    'Texture_',
    'AreaShape_SpatialMoment_',
    'AreaShape_CentralMoment_',
    'AreaShape_NormalizedMoment_',
    'AreaShape_HuMoment_',
    'AreaShape_InertiaTensor',
)

# CellProfiler fills the radius arrays with zeros first, so their unused end is 0.0, not nan.
ZERO_PADDED = {'AreaShape_MaximumRadius', 'AreaShape_MeanRadius', 'AreaShape_MedianRadius'}

# Thread settings of the numerical libraries. Each SEGMENT worker gets its share of the task's cores.
THREADS = ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS')

# Fraction of the GPU memory that all SEGMENT workers together may use. The rest is for CUDA itself.
GPU_MEMORY = 0.9


def checksum(path):
    """Return the SHA-256 checksum of a file as hexadecimal text.

    Parameters
    ----------
    path : str or Path
        The file.

    Returns
    -------
    str
        The checksum.
    """
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def realign(output, contract):
    """Move shifted CellProfiler values back to the objects they belong to.

    For each image and object type, the mask gives the pixel count of every object. If all
    objects have pixels, nothing moved. Otherwise the first values of each shifted column belong
    to the objects with pixels, in order, and the objects without pixels get nan.

    Parameters
    ----------
    output : Path
        The batch folder with ``features/`` and ``mask_manifest.csv``.
    contract : dict
        The contract from PREPARE. Its ``objects`` are the object types to check.

    Returns
    -------
    list of dict
        One correction per image and object type, for validation.json.

    Raises
    ------
    ValueError
        If the values do not show the known shift pattern. Then the cause is something else,
        and the data must not be changed.
    """
    masks = read_csv(output / 'mask_manifest.csv')
    corrections = []
    for obj in contract['objects']:
        path = output / 'features' / f'{obj}.csv'
        with path.open(newline='') as stream:
            reader = csv.reader(stream)
            header = next(reader)
            table = list(reader)
        col = {name: i for i, name in enumerate(header)}
        shifted = [i for name, i in col.items() if name in SHIFTED or name.startswith(SHIFTED_PREFIXES)]
        if not shifted:
            continue
        for mask in (m for m in masks if m['ObjectType'] == obj):
            # The rows of this image, sorted by object number. The numbers must run 1, 2, ..., N.
            image = sorted((r for r in table if r[col['ImageNumber']] == mask['ImageNumber']), key=lambda r: int(r[col['ObjectNumber']]))
            if [int(r[col['ObjectNumber']]) for r in image] != list(range(1, len(image) + 1)):
                raise ValueError(f'{obj}: object numbers are not 1..N in image {mask["ImageNumber"]}')

            # Pixel count of each object (labels 1..N). An object with 0 pixels is empty.
            pixels = np.bincount(tifffile.imread(output / mask['MaskPath']).ravel(), minlength=len(image) + 1)[1:]
            if len(pixels) != len(image):
                raise ValueError(f'{obj}: mask labels exceed measurement rows in image {mask["ImageNumber"]}')
            present = np.flatnonzero(pixels)
            if len(present) == len(image):
                continue
            for i in shifted:
                # Known pattern: one empty value at the end for each empty object.
                pad = '0.0' if header[i] in ZERO_PADDED else 'nan'
                if {r[i] for r in image[len(present) :]} != {pad}:
                    raise ValueError(f'{obj}: {header[i]} does not show the known CP 4.2.8.1 shift; review before use')

                # Give the first values to the objects with pixels, in order. Empty objects get nan.
                values = [r[i] for r in image[: len(present)]]
                for r in image:
                    r[i] = 'nan'
                for j, value in zip(present, values):
                    image[j][i] = value
            corrections.append(
                dict(
                    object=obj,
                    image_number=mask['ImageNumber'],
                    acquisition=mask['Acquisition'],
                    empty_objects=[int(j) + 1 for j in np.flatnonzero(pixels == 0)],
                    columns=len(shifted),
                )
            )

        # Write the table again only if a value moved. The row order stays the same.
        if any(c['object'] == obj for c in corrections):
            with path.open('w', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow(header)
                writer.writerows(table)
    return corrections


def read_mask(path, entry, loaded):
    """Read one saved mask and check that it belongs to its image set and its files.

    Parameters
    ----------
    path : Path
        The TIFF file that SaveLabelMasks wrote.
    entry : dict
        Its row of mask_manifest.csv: Plate, Batch, Acquisition and ObjectType.
    loaded : dict
        The manifest row of the image set, with the FileName_ and PathName_ of every loaded file.

    Returns
    -------
    numpy.ndarray
        The labels.

    Raises
    ------
    ValueError
        If the mask is not a 2D uint32 image, or its provenance names another object, image set
        or file than this image set loaded.
    """
    with tifffile.TiffFile(path) as tiff:
        labels = tiff.asarray()
        provenance = json.loads(tiff.pages[0].description)
    if labels.dtype != np.uint32 or labels.ndim != 2:
        raise ValueError(f'Mask is not a uint32 label image: {entry}')

    # The mask must name its own image set and exactly the files this batch loaded for it.
    named = {k: provenance['metadata'][k] for k in ('Plate', 'Batch', 'Acquisition')}
    files = provenance['source_files']
    if (
        provenance['object'] != entry['ObjectType']
        or named != {k: entry[k] for k in named}
        or not files
        or any((loaded['FileName_' + n], loaded['PathName_' + n]) != (f['file'], f['folder']) for n, f in files.items())
    ):
        raise ValueError(f'Mask provenance does not match its image set: {path}')
    return labels


def validate_analysis(output, rows, contract):
    """Check the tables and masks of one batch against its manifest.

    Checks:

    - Image.csv has exactly the image sets of the manifest, and no module error.
    - Each image set has one mask per object type. The mask names its image set and exactly
      the files that this batch loaded for it.
    - Object numbers run 1..N, and N equals ``Count_<Object>`` in Image.csv.
    - ``AreaShape_Area`` equals the pixel count of the object in its mask, and
      ``AreaShape_Center_X`` equals ``Location_Center_X``. Together these prove that every row
      belongs to the right object.

    Parameters
    ----------
    output : Path
        The batch folder with ``features/``, ``masks/`` and ``mask_manifest.csv``.
    rows : list of dict
        The manifest rows of this batch, with the illumination file names.
    contract : dict
        The contract from PREPARE.

    Returns
    -------
    dict
        A summary for validation.json: image sets, masks, object types, empty objects.

    Raises
    ------
    ValueError
        On the first check that fails.
    """
    images = read_csv(output / 'features' / 'Image.csv')
    key = lambda r: tuple(r['Metadata_' + k] for k in ('Plate', 'Batch', 'Acquisition'))  # noqa: E731
    expected = {key(r) for r in rows}
    if len(images) != len(rows) or {key(r) for r in images} != expected:
        raise ValueError('Exported image sets do not match the assigned manifest exactly')
    if any(float(v) != 0 for row in images for k, v in row.items() if k.startswith('ModuleError_') and v):
        raise ValueError('CellProfiler reported a module error in Image.csv')

    # One mask per image set and object type, no more and no less.
    masks = read_csv(output / 'mask_manifest.csv')
    expected_masks = {(p, b, a, obj) for p, b, a in expected for obj in contract['objects']}
    actual = {(r['Plate'], r['Batch'], r['Acquisition'], r['ObjectType']) for r in masks}
    if actual != expected_masks or len(actual) != len(masks):
        raise ValueError(f'Missing, duplicate or unexpected masks: missing={expected_masks - actual}, extra={actual - expected_masks}')
    image_by_number = {r['ImageNumber']: r for r in images}
    loaded_by_acquisition = {r['Metadata_Acquisition']: r for r in rows}
    tables = {obj: read_csv(output / 'features' / f'{obj}.csv') for obj in contract['objects']}
    empty = {}
    for row in masks:
        obj, number = row['ObjectType'], row['ImageNumber']
        image = image_by_number[number]
        if (row['Plate'], row['Batch'], row['Acquisition']) != key(image):
            raise ValueError(f'Mask/image acquisition mismatch: {row}')
        labels = read_mask(output / row['MaskPath'], row, loaded_by_acquisition[row['Acquisition']])

        # Compare the rows of this image with the labels in its mask. Objects without pixels keep
        # their rows and numbers (e.g. a cytoplasm that its nucleus covers fully).
        objects = [r for r in tables[obj] if r['ImageNumber'] == number]
        ids = [int(r['ObjectNumber']) for r in objects]
        pixels = np.bincount(labels.ravel(), minlength=len(ids) + 1)
        present = set(np.flatnonzero(pixels)) - {0}
        if sorted(ids) != list(range(1, len(ids) + 1)) or not present <= set(ids) or len(ids) != float(image['Count_' + obj]):
            raise ValueError(f'Mask labels, measurement rows and count disagree: {obj}, image {number}')
        if len(present) != int(row['LabelCount']):
            raise ValueError(f'Mask manifest label count disagrees: {row}')
        empty[obj] = empty.get(obj, 0) + len(ids) - len(present)
        for r in objects:
            n = int(r['ObjectNumber'])
            if 'AreaShape_Area' in r and not (float(r['AreaShape_Area']) == pixels[n] if pixels[n] else r['AreaShape_Area'] == 'nan'):
                raise ValueError(f'{obj}: AreaShape_Area does not match mask pixels for object {n}, image {number}')
            if (
                'AreaShape_Center_X' in r
                and 'Location_Center_X' in r
                and not np.isclose(float(r['AreaShape_Center_X']), float(r['Location_Center_X']), rtol=0, atol=1e-6, equal_nan=True)
            ):
                raise ValueError(f'{obj}: AreaShape_Center_X disagrees with Location_Center_X for object {n}, image {number}')
    return {'image_sets': len(images), 'masks': len(masks), 'objects': contract['objects'], 'empty_objects': empty}


def add_illumination(rows, folder, plate, contract):
    """Check the correction files of the plate, and add them to every manifest row.

    Parameters
    ----------
    rows : list of dict
        The manifest rows of the batch. Changed in place.
    folder : Path
        The ILLUMINATION output folder of the plate.
    plate : str
        The plate of this batch.
    contract : dict
        The contract from PREPARE. Its ``corrections`` name the functions.

    Returns
    -------
    dict
        Function name -> plate and checksum, for validation.json.

    Raises
    ------
    ValueError
        If the folder belongs to another plate, or a file does not have its recorded checksum.
    """
    saved = json.loads((folder / 'provenance.json').read_text())
    if saved['plate'] != plate:
        raise ValueError('Illumination plate does not match analysis plate')
    provenance = {}
    for name in contract['corrections']:
        function = (folder / (name + '.npy')).resolve()
        if checksum(function) != saved['sha256'][name]:
            raise ValueError(f'Illumination checksum mismatch: {function}')
        provenance[name] = {'plate': plate, 'sha256': saved['sha256'][name]}

        # LoadData reads a correction file like an image: it needs a file name and a folder.
        for row in rows:
            row['FileName_' + name] = function.name
            row['PathName_' + name] = str(function.parent)
    return provenance


def cellprofiler(pipeline, data_file, output, temp, plugins, log, env=None):
    """Start CellProfiler headless on a LoadData CSV file. Its output goes to the log.

    Parameters
    ----------
    pipeline : Path
        The .cppipe file.
    data_file : Path
        The LoadData CSV file.
    output : Path
        The Default Output Folder. It is created.
    temp : Path
        The temporary folder. It is created.
    plugins : Path
        The plugin folder.
    log : Path
        The log file.
    env : dict, optional
        The environment of the process. Default: the environment of this process.

    Returns
    -------
    subprocess.Popen
        The running process.
    """
    for folder in (output, temp):
        folder.mkdir(parents=True, exist_ok=True)
    command = [
        'cellprofiler',
        '-c',
        '-r',
        '-p',
        str(pipeline.resolve()),
        '--data-file',
        str(data_file.resolve()),
        '-i',
        str(Path.cwd()),
        '-o',
        str(output.resolve()),
        '-t',
        str(temp.resolve()),
        '--plugins-directory',
        str(plugins.resolve()),
        '--log-level',
        'INFO',
    ]
    with log.open('w') as stream:
        return subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, env=env)


def check_log(code, log):
    """Raise if CellProfiler exited with an error or logged a Python exception.

    Parameters
    ----------
    code : int
        The exit code.
    log : Path
        The log file of the run.

    Raises
    ------
    ValueError
        If the run failed. CellProfiler can log a Python error and still exit with 0.
    """
    text = log.read_text()
    if code:
        print(text[-8000:])
        raise ValueError(f'CellProfiler failed with exit code {code}: {log}')
    if 'Traceback (most recent call last)' in text:
        raise ValueError(f'CellProfiler logged an exception: {log}')


def run_cellprofiler(args, rows, output, logs):
    """Run CellProfiler headless on the manifest rows, and record time and peak memory.

    Parameters
    ----------
    args : argparse.Namespace
        The command-line arguments.
    rows : list of dict
        The LoadData rows. They are written to ``load_data.csv``.
    output : Path
        The CellProfiler output folder.
    logs : Path
        The folder for the log and ``<batch>.metrics.json``.

    Returns
    -------
    dict
        The metrics: time, peak memory, image sets per minute, exit code.

    Raises
    ------
    ValueError
        If CellProfiler exits with an error, or logs a Python exception.
    """
    write_csv('load_data.csv', rows)
    log = logs / f'{args.batch}.log'
    start = time.monotonic()
    code = cellprofiler(args.pipeline, Path('load_data.csv'), output, Path('tmp'), args.plugins, log).wait()
    elapsed = time.monotonic() - start
    metrics = dict(
        plate=args.plate,
        batch=args.batch,
        kind=args.kind,
        elapsed_seconds=elapsed,
        peak_rss_kib=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
        image_sets=len(rows),
        sets_per_minute=60 * len(rows) / elapsed,
        exit_code=code,
    )
    (logs / f'{args.batch}.metrics.json').write_text(json.dumps(metrics, indent=2))
    check_log(code, log)
    return metrics


# ---------------------------------------------------------------------------------------------
# SEGMENT: RunCellpose on a GPU or a CPU, several CellProfiler workers per task
# ---------------------------------------------------------------------------------------------


def split(rows, workers):
    """Cut the rows into consecutive parts, one per worker.

    Parameters
    ----------
    rows : list
        The manifest rows, in plate order.
    workers : int
        The number of workers.

    Returns
    -------
    list of list
        At most ``workers`` parts, none empty. Their sizes differ by at most one, and joining
        them gives the rows back in the same order.
    """
    count = min(workers, len(rows))
    size, extra = divmod(len(rows), count)
    parts, start = [], 0
    for k in range(count):
        end = start + size + (k < extra)
        parts.append(rows[start:end])
        start = end
    return parts


def segmentation_pipeline(source, target, device, workers, plugins):
    """Write the SEGMENT pipeline of this task: RunCellpose on the chosen device.

    On a GPU, all workers share the GPU memory: each may use GPU_MEMORY / workers of it
    (the RunCellpose setting "GPU memory share for each worker"). These two settings change
    where Cellpose runs, not what it computes.

    Parameters
    ----------
    source : Path
        pipelines/segmentation.cppipe from PREPARE (GPU off).
    target : Path
        The pipeline file to write, in the task folder. It must not be ``source`` or a link to it:
        Nextflow stages ``source`` as a link into the PREPARE folder, which other tasks read.
    device : {'cpu', 'gpu'}
        Where Cellpose runs.
    workers : int
        The number of workers that run at the same time.
    plugins : Path
        The plugin folder (RunCellpose, SaveLabelMasks).

    Returns
    -------
    bool
        True if a RunCellpose module uses the built-in cpsam model.
    """
    from cellprofiler_core.preferences import set_headless, set_plugin_directory

    set_headless()
    set_plugin_directory(str(plugins.resolve()))
    sys.path.insert(0, str(plugins.resolve()))
    from prepare import load_pipeline

    if target.resolve() == source.resolve():
        raise ValueError(f'The SEGMENT pipeline copy would overwrite its input: {source}')
    pipeline = load_pipeline(source)
    cellpose = [m for m in pipeline.modules() if m.module_name == 'RunCellpose']
    for module in cellpose:
        module.use_gpu.value = device == 'gpu'
        module.manual_GPU_memory_share.value = GPU_MEMORY / workers
    with target.open('w') as stream:
        pipeline.dump(stream)
    return any(m.mode_v4.value != 'custom' for m in cellpose)


def gpu_monitor(log):
    """Record the use of the visible GPUs every second, with nvidia-smi, until the process stops.

    Parameters
    ----------
    log : Path
        The CSV file to write: time, GPU name, utilization (%), memory used and total (MiB).

    Returns
    -------
    subprocess.Popen
        The nvidia-smi process.
    """
    command = [
        'nvidia-smi',
        '--query-gpu=timestamp,name,utilization.gpu,memory.used,memory.total',
        '--format=csv,noheader,nounits',
        '-l',
        '1',
    ]
    if os.environ.get('CUDA_VISIBLE_DEVICES'):
        command += ['-i', os.environ['CUDA_VISIBLE_DEVICES']]
    with log.open('w') as stream:
        return subprocess.Popen(command, stdout=stream, stderr=subprocess.DEVNULL)


def gpu_summary(log):
    """Summarize the log of ``gpu_monitor()``: GPU name, mean utilization and peak memory.

    Parameters
    ----------
    log : Path
        The CSV file of ``gpu_monitor()``.

    Returns
    -------
    dict
        Empty if nvidia-smi wrote no sample.
    """
    samples = [line.split(', ') for line in log.read_text().splitlines() if line.count(', ') == 4]
    if not samples:
        return {}
    return dict(
        gpu=samples[0][1],
        gpu_samples=len(samples),
        gpu_utilization_mean=round(sum(float(s[2]) for s in samples) / len(samples), 1),
        gpu_memory_peak_mib=max(float(s[3]) for s in samples),
        gpu_memory_total_mib=float(samples[0][4]),
    )


def run_segmentation(args, rows, logs):
    """Run the SEGMENT pipeline with ``--workers`` CellProfiler processes at the same time.

    Each worker gets a consecutive part of the rows (see ``split()``) and its own folder,
    workers/NN/, and a share of the task's cores for the numerical libraries.

    Parameters
    ----------
    args : argparse.Namespace
        The command-line arguments: pipeline, device, workers, cpus, plugins, plate, batch.
    rows : list of dict
        The manifest rows of the group, with the illumination file names.
    logs : Path
        The folder for the worker logs, <segment>.gpu.csv and <segment>.metrics.json.

    Returns
    -------
    metrics : dict
        Time, image sets per minute, workers and, on a GPU, its mean utilization and peak memory.
    outputs : list of Path
        The output folder of each worker, in row order.

    Raises
    ------
    ValueError
        If the device is 'gpu' but no GPU is visible, or a worker fails.
    """
    # Without a GPU, Cellpose would use the CPU without an error, and take many times longer.
    if args.device == 'gpu':
        import torch

        if not torch.cuda.is_available():
            raise ValueError('--segmentation gpu, but this task sees no GPU. Request a GPU for SEGMENT, or use --segmentation cpu')
    # The copy goes to workers/, not to segmentation.cppipe: that name is the staged PREPARE file.
    pipeline = Path('workers/segmentation.cppipe')
    pipeline.parent.mkdir(parents=True, exist_ok=True)
    if segmentation_pipeline(args.pipeline, pipeline, args.device, args.workers, args.plugins):
        # Get the model once, before the workers start, so that they do not download it at the same time.
        from cellpose.models import cache_CPSAM_model_path

        cache_CPSAM_model_path()

    parts = split(rows, args.workers)
    threads = str(max(1, args.cpus // len(parts)))
    env = dict(os.environ, **{name: threads for name in THREADS})
    monitor = gpu_monitor(logs / f'{args.batch}.gpu.csv') if args.device == 'gpu' and shutil.which('nvidia-smi') else None
    start = time.monotonic()
    workers = []
    for k, part in enumerate(parts, 1):
        folder = Path('workers') / f'{k:02d}'
        write_csv(folder / 'load_data.csv', part)
        log = logs / f'{args.batch}.worker{k:02d}.log'
        process = cellprofiler(pipeline, folder / 'load_data.csv', folder / 'out', folder / 'tmp', args.plugins, log, env)
        workers.append((process, log, folder / 'out'))
    codes = [process.wait() for process, _, _ in workers]
    elapsed = time.monotonic() - start
    if monitor:
        monitor.terminate()
        monitor.wait()

    metrics = dict(
        plate=args.plate,
        batch=args.batch,
        kind=args.kind,
        device=args.device,
        workers=len(parts),
        threads_per_worker=int(threads),
        elapsed_seconds=elapsed,
        image_sets=len(rows),
        sets_per_minute=60 * len(rows) / elapsed,
        exit_codes=codes,
        peak_rss_kib_largest_worker=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
    )
    if monitor:
        metrics.update(gpu_summary(logs / f'{args.batch}.gpu.csv'))
    (logs / f'{args.batch}.metrics.json').write_text(json.dumps(metrics, indent=2))
    for code, (_, log, _) in zip(codes, workers):
        check_log(code, log)
    return metrics, [out for _, _, out in workers]


def collect_masks(outputs, rows, objects, destination, plate, segment):
    """Check the masks of all workers, and sort them into one folder per batch.

    Parameters
    ----------
    outputs : list of Path
        The worker output folders, each with mask_manifest.csv and masks/.
    rows : list of dict
        The manifest rows of the group, with the illumination file names.
    objects : list of str
        The objects that RunCellpose makes (``contract['segmentation']``).
    destination : Path
        result/segmentation. It gets <batch>/masks/, <batch>/mask_manifest.csv and
        <batch>/validation.json (written last: ANALYSIS uses a folder only if it has it).
    plate : str
        The plate of the task.
    segment : str
        The name of the group, for validation.json.

    Returns
    -------
    dict
        A summary for the task log: segment, batches and number of masks.

    Raises
    ------
    ValueError
        If a mask is missing, saved twice or unexpected, names another image set or other files,
        or its label count disagrees with mask_manifest.csv.
    """
    loaded = {(r['Metadata_Batch'], r['Metadata_Acquisition']): r for r in rows}
    expected = {key + (obj,) for key in loaded for obj in objects}
    found = {}
    for out in outputs:
        manifest = out / 'mask_manifest.csv'
        for entry in read_csv(manifest) if manifest.exists() else []:
            key = (entry['Batch'], entry['Acquisition'], entry['ObjectType'])
            if key in found or entry['Plate'] != plate:
                raise ValueError(f'SEGMENT mask saved twice (duplicate) or for another plate: {entry}')
            found[key] = (out, entry)
    if set(found) != expected:
        raise ValueError(
            f'SEGMENT masks are missing or unexpected: missing={sorted(expected - set(found))[:5]}, '
            f'extra={sorted(set(found) - expected)[:5]}'
        )

    # Go through the image sets in manifest order, so each batch keeps its order.
    batches = {}
    for (batch, acquisition), row in loaded.items():
        for obj in objects:
            out, entry = found[(batch, acquisition, obj)]
            labels = read_mask(out / entry['MaskPath'], entry, row)
            if np.count_nonzero(np.unique(labels)) != int(entry['LabelCount']):
                raise ValueError(f'SEGMENT mask label count disagrees with its manifest: {entry}')
            target = destination / batch / 'masks' / Path(entry['MaskPath']).name
            target.parent.mkdir(parents=True, exist_ok=True)
            (out / entry['MaskPath']).rename(target)
            batches.setdefault(batch, []).append(
                dict(
                    Plate=plate,
                    Batch=batch,
                    Acquisition=acquisition,
                    ObjectType=obj,
                    MaskPath='masks/' + target.name,
                    LabelCount=entry['LabelCount'],
                )
            )
    for batch, entries in batches.items():
        write_csv(destination / batch / 'mask_manifest.csv', entries, list(entries[0]))
        summary = dict(
            plate=plate,
            batch=batch,
            segment=segment,
            image_sets=len({e['Acquisition'] for e in entries}),
            masks=len(entries),
            objects=objects,
            labels={obj: sum(int(e['LabelCount']) for e in entries if e['ObjectType'] == obj) for obj in objects},
        )
        (destination / batch / 'validation.json').write_text(json.dumps(summary, indent=2))
    return dict(segment=segment, batches=list(batches), masks=sum(map(len, batches.values())))


def check_segmentation(folder, plate, batch, rows, objects):
    """Check, before ANALYSIS runs, that a SEGMENT folder holds the masks of exactly this batch.

    Parameters
    ----------
    folder : Path
        The SEGMENT folder of the batch.
    plate, batch : str
        The plate and batch of the ANALYSIS task.
    rows : list of dict
        The manifest rows of the batch.
    objects : list of str
        The objects that RunCellpose makes.

    Raises
    ------
    ValueError
        If the folder did not pass its checks, is for another plate or batch, or does not have
        one mask per image set and object.
    """
    validation = folder / 'validation.json'
    if not validation.exists():
        raise ValueError(f'The segmentation of {batch} did not pass its checks: {folder}')
    summary = json.loads(validation.read_text())
    if (summary['plate'], summary['batch']) != (plate, batch):
        raise ValueError(f'Segmentation folder is for {summary["plate"]}/{summary["batch"]}, not {plate}/{batch}')
    masks = sorted((e['Acquisition'], e['ObjectType']) for e in read_csv(folder / 'mask_manifest.csv'))
    if masks != sorted((r['Metadata_Acquisition'], obj) for r in rows for obj in objects):
        raise ValueError(f'Segmentation masks of {batch} are not for the image sets of this batch')


def compare_masks(output, segmentation, objects):
    """Check that ANALYSIS used the SEGMENT masks unchanged, label for label.

    ANALYSIS saves a mask of every object at the end, also of the objects that LoadLabelMasks
    loaded. For those, the saved mask must equal the SEGMENT mask.

    Parameters
    ----------
    output : Path
        The ANALYSIS batch folder, with mask_manifest.csv and masks/.
    segmentation : Path
        The SEGMENT folder of the batch.
    objects : list of str
        The objects that RunCellpose makes.

    Returns
    -------
    int
        The number of masks compared.

    Raises
    ------
    ValueError
        If a mask is missing in ANALYSIS or differs from the SEGMENT mask.
    """
    saved = {(e['Acquisition'], e['ObjectType']): e for e in read_csv(output / 'mask_manifest.csv')}
    compared = 0
    for entry in read_csv(segmentation / 'mask_manifest.csv'):
        if entry['ObjectType'] not in objects:
            continue
        final = saved.get((entry['Acquisition'], entry['ObjectType']))
        if final is None or not np.array_equal(
            tifffile.imread(segmentation / entry['MaskPath']), tifffile.imread(output / final['MaskPath'])
        ):
            raise ValueError(f'Mask of {entry["ObjectType"]} in {entry["Acquisition"]} differs between SEGMENT and ANALYSIS')
        compared += 1
    return compared


def check_illumination(output, rows, plate, contract):
    """Check the correction functions, and write provenance.json with their checksums.

    Each function must be one of the expected files, have the shape of the images, and hold only
    finite values above 0. The analysis batches check the checksums before they use the files.

    Parameters
    ----------
    output : Path
        The ILLUMINATION output folder.
    rows : list of dict
        The manifest rows of the plate.
    plate : str
        The plate.
    contract : dict
        The contract from PREPARE. Its ``calculated`` names the functions and their images.

    Raises
    ------
    ValueError
        If a file is missing or extra, or a function has a wrong shape or value.
    """
    if {p.name for p in output.glob('*.npy')} != {name + '.npy' for name in contract['calculated']}:
        raise ValueError('Illumination output functions differ from the pipeline contract')
    sums = {}
    for name, image in contract['calculated'].items():
        path = output / (name + '.npy')
        function = np.load(path, allow_pickle=False)
        with tifffile.TiffFile(Path(rows[0]['PathName_' + image]) / rows[0]['FileName_' + image]) as tiff:
            shape = tiff.series[0].shape
        if function.shape != shape or not np.isfinite(function).all() or np.min(function) <= 0:
            raise ValueError(f'Invalid plate correction function: {path}')
        sums[name] = checksum(path)
    (output / 'provenance.json').write_text(json.dumps(dict(plate=plate, image_sets=len(rows), sha256=sums), indent=2))


def finish_analysis(output, rows, contract, provenance, logs, batch):
    """Correct and check the outputs of one batch, then put them where MERGE and Nextflow read them.

    Parameters
    ----------
    output : Path
        The batch folder.
    rows : list of dict
        The manifest rows of the batch, with the illumination file names.
    contract : dict
        The contract from PREPARE.
    provenance : dict
        The checked correction files, from ``add_illumination()``.
    logs : Path
        The folder for ``<batch>.validation.json``.
    batch : str
        The batch name.

    Raises
    ------
    ValueError
        If a check of ``realign()``, ``validate_analysis()`` or ``compare_masks()`` fails.
    """
    corrections = realign(output, contract)
    qc = validate_analysis(output, rows, contract)
    qc['illumination'] = provenance
    qc['realigned'] = corrections
    if contract.get('segmentation'):
        qc['segmentation_masks_compared'] = compare_masks(output, Path('segmentation'), contract['segmentation'])

    # Compress the checked tables. MERGE reads them as .csv.gz. This halves the space in work/.
    for table in (output / 'features').glob('*.csv'):
        with table.open('rb') as source, gzip.open(table.with_suffix('.csv.gz'), 'wb', compresslevel=1) as target:
            shutil.copyfileobj(source, target)
        table.unlink()

    # MERGE uses a batch only if it has validation.json, so write that file last.
    for path in (output / 'validation.json', logs / f'{batch}.validation.json'):
        path.write_text(json.dumps(qc, indent=2))

    # Nextflow does not publish files inside another output folder, so the masks move beside it.
    (output / 'masks').rename(Path('result/masks'))


def read_manifests(args):
    """Read the manifest rows of the task, and check that they are its plate and batches.

    Parameters
    ----------
    args : argparse.Namespace
        The command-line arguments.

    Returns
    -------
    list of dict
        The rows. A SEGMENT task gets the rows of all its batch manifests, in batch order.

    Raises
    ------
    ValueError
        If the rows are not exactly the task's plate, or (analysis) not its batch, or (SEGMENT)
        a manifest is not exactly one batch.
    """
    if args.kind != 'segmentation' and len(args.manifest) != 1:
        raise ValueError(f'{args.kind} takes one --manifest')
    parts = [read_csv(path) for path in sorted(args.manifest, key=lambda p: p.name)]
    rows = [row for part in parts for row in part]
    if not rows or {r['Metadata_Plate'] for r in rows} != {args.plate}:
        raise ValueError('Task manifest must contain exactly its assigned plate')
    if args.kind == 'analysis' and {r['Metadata_Batch'] for r in rows} != {args.batch}:
        raise ValueError('Task manifest has the wrong batch')
    if args.kind == 'segmentation':
        batches = [{r['Metadata_Batch'] for r in part} for part in parts]
        if any(len(b) != 1 for b in batches) or len(set().union(*batches)) != len(parts):
            raise ValueError('Each SEGMENT manifest must hold exactly one batch, and each batch once')
    return rows


def run(args):
    """Run one illumination, segmentation or analysis task and write its outputs under ``result/``.

    Parameters
    ----------
    args : argparse.Namespace
        The command-line arguments (see ``main()``).

    Raises
    ------
    ValueError
        If an input is wrong, CellProfiler fails, or a check fails.
    """
    rows = read_manifests(args)
    contract = json.loads(args.contract.read_text())
    logs = Path('result/logs')
    logs.mkdir(parents=True, exist_ok=True)

    if args.kind == 'illumination':
        output = Path('result/illumination')
        output.mkdir(parents=True, exist_ok=True)
        metrics = run_cellprofiler(args, rows, output, logs)
        check_illumination(output, rows, args.plate, contract)

    elif args.kind == 'segmentation':
        provenance = add_illumination(rows, args.illumination, args.plate, contract)
        metrics, outputs = run_segmentation(args, rows, logs)
        summary = collect_masks(outputs, rows, contract['segmentation'], Path('result/segmentation'), args.plate, args.batch)
        (logs / f'{args.batch}.validation.json').write_text(json.dumps(dict(summary, illumination=provenance), indent=2))

    else:
        output = Path('result/analysis') / args.batch
        output.mkdir(parents=True, exist_ok=True)
        provenance = add_illumination(rows, args.illumination, args.plate, contract)

        # With RunCellpose, LoadLabelMasks reads the masks from segmentation/ in the task folder.
        if contract.get('segmentation'):
            if not args.segmentation:
                raise ValueError('The analysis pipeline has RunCellpose: give the SEGMENT folder with --segmentation')
            check_segmentation(args.segmentation, args.plate, args.batch, rows, contract['segmentation'])
            if not Path('segmentation').exists():
                Path('segmentation').symlink_to(args.segmentation.resolve())
        metrics = run_cellprofiler(args, rows, output, logs)
        finish_analysis(output, rows, contract, provenance, logs, args.batch)
    write_csv(logs / f'{args.batch}.load_data.csv', rows)
    print(json.dumps(metrics))


def main():
    """Parse the arguments and run the task. Exit with code 2 and one line on a failed check."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('kind', choices=['illumination', 'segmentation', 'analysis'])
    parser.add_argument('--plate', required=True)
    parser.add_argument('--batch', default='illumination', help='the batch, or the group name of a SEGMENT task')
    parser.add_argument('--manifest', type=Path, nargs='+', required=True, help='SEGMENT: one manifest per batch')
    parser.add_argument('--pipeline', type=Path, required=True)
    parser.add_argument('--contract', type=Path, required=True)
    parser.add_argument('--plugins', type=Path, default=Path('plugins'))
    parser.add_argument('--illumination', type=Path)
    parser.add_argument('--segmentation', type=Path, help='analysis: the SEGMENT folder of this batch')
    parser.add_argument('--device', choices=['cpu', 'gpu'], default='cpu', help='SEGMENT: where Cellpose runs')
    parser.add_argument('--workers', type=int, default=1, help='SEGMENT: CellProfiler processes at the same time')
    parser.add_argument('--cpus', type=int, default=1, help='SEGMENT: cores of the task, shared by the workers')
    args = parser.parse_args()
    try:
        if args.workers < 1 or args.cpus < 1:
            raise ValueError('--workers and --cpus must be at least 1')
        run(args)
    except (ValueError, FileNotFoundError, KeyError) as error:
        parser.exit(2, f'Task validation failed: {error}\n')


if __name__ == '__main__':
    main()
