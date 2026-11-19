#!/usr/bin/env python3
"""ILLUMINATION and ANALYSIS steps: run one CellProfiler task, then check what it wrote.

illumination (one task per plate)
  In:  the plate manifest (all image sets of the plate) and the illumination pipeline.
  Out: result/illumination/Illum<Channel>.npy and provenance.json (plate and SHA-256 per file).
analysis (one task per batch)
  In:  the batch manifest, the analysis pipeline and the illumination folder of the same plate.
  Out: result/analysis/<batch>/features/*.csv.gz, validation.json, and result/masks/*.tiff.
Both write result/logs/<batch>.log, <batch>.metrics.json and <batch>.load_data.csv.

What happens inside one analysis task:
  1. Check each .npy file against the checksum in provenance.json of the same plate.
  2. Add the .npy file names to every manifest row. Write load_data.csv.
  3. Run CellProfiler headless on load_data.csv.
  4. realign(): move shifted AreaShape and Texture values back to their objects.
  5. validate_analysis(): check the tables and masks against the manifest.
  6. Compress the tables and move the masks next to the batch folder.
"""
import argparse
import csv
import gzip
import hashlib
import json
import resource
import shutil
import subprocess
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
SHIFTED = {'AreaShape_' + f for f in (
    'Area', 'Perimeter', 'MajorAxisLength', 'MinorAxisLength', 'Eccentricity', 'Orientation', 'Center_X',
    'Center_Y', 'BoundingBoxArea', 'BoundingBoxMinimum_X', 'BoundingBoxMaximum_X', 'BoundingBoxMinimum_Y',
    'BoundingBoxMaximum_Y', 'FormFactor', 'Extent', 'Solidity', 'Compactness', 'EulerNumber',
    'MaximumRadius', 'MeanRadius', 'MedianRadius', 'ConvexArea', 'EquivalentDiameter')}
SHIFTED_PREFIXES = ('Texture_', 'AreaShape_SpatialMoment_', 'AreaShape_CentralMoment_', 'AreaShape_NormalizedMoment_',
                    'AreaShape_HuMoment_', 'AreaShape_InertiaTensor')

# CellProfiler fills the radius arrays with zeros first, so their unused end is 0.0, not nan.
ZERO_PADDED = {'AreaShape_MaximumRadius', 'AreaShape_MeanRadius', 'AreaShape_MedianRadius'}


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
            image = sorted((r for r in table if r[col['ImageNumber']] == mask['ImageNumber']),
                           key=lambda r: int(r[col['ObjectNumber']]))
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
                if {r[i] for r in image[len(present):]} != {pad}:
                    raise ValueError(f'{obj}: {header[i]} does not show the known CP 4.2.8.1 shift; review before use')

                # Give the first values to the objects with pixels, in order. Empty objects get nan.
                values = [r[i] for r in image[:len(present)]]
                for r in image:
                    r[i] = 'nan'
                for j, value in zip(present, values):
                    image[j][i] = value
            corrections.append(dict(object=obj, image_number=mask['ImageNumber'], acquisition=mask['Acquisition'],
                                    empty_objects=[int(j) + 1 for j in np.flatnonzero(pixels == 0)], columns=len(shifted)))

        # Write the table again only if a value moved. The row order stays the same.
        if any(c['object'] == obj for c in corrections):
            with path.open('w', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow(header)
                writer.writerows(table)
    return corrections


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
        with tifffile.TiffFile(output / row['MaskPath']) as tiff:
            labels = tiff.asarray()
            provenance = json.loads(tiff.pages[0].description)
        if labels.dtype != np.uint32 or labels.ndim != 2:
            raise ValueError(f'Mask is not a uint32 label image: {row}')

        # The mask must name its own image set and exactly the files this batch loaded for it.
        loaded = loaded_by_acquisition[row['Acquisition']]
        named = {k: provenance['metadata'][k] for k in ('Plate', 'Batch', 'Acquisition')}
        files = provenance['source_files']
        if provenance['object'] != obj or named != dict(Plate=row['Plate'], Batch=row['Batch'], Acquisition=row['Acquisition']) \
                or not files or any((loaded['FileName_' + n], loaded['PathName_' + n]) != (f['file'], f['folder']) for n, f in files.items()):
            raise ValueError(f'Mask provenance does not match its image set: {row["MaskPath"]}')

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
            if 'AreaShape_Center_X' in r and 'Location_Center_X' in r and not np.isclose(
                    float(r['AreaShape_Center_X']), float(r['Location_Center_X']), rtol=0, atol=1e-6, equal_nan=True):
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
    temp = Path('tmp')
    temp.mkdir(exist_ok=True)
    log = logs / f'{args.batch}.log'
    command = ['cellprofiler', '-c', '-r', '-p', str(args.pipeline.resolve()),
               '--data-file', str(Path('load_data.csv').resolve()), '-i', str(Path.cwd()),
               '-o', str(output.resolve()), '-t', str(temp.resolve()),
               '--plugins-directory', str(args.plugins.resolve()), '--log-level', 'INFO']
    start = time.monotonic()
    with log.open('w') as stream:
        result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT)
    elapsed = time.monotonic() - start
    metrics = dict(plate=args.plate, batch=args.batch, kind=args.kind, elapsed_seconds=elapsed,
                   peak_rss_kib=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss, image_sets=len(rows),
                   sets_per_minute=60 * len(rows) / elapsed, exit_code=result.returncode)
    (logs / f'{args.batch}.metrics.json').write_text(json.dumps(metrics, indent=2))
    if result.returncode:
        print(log.read_text()[-8000:])
        raise ValueError(f'CellProfiler failed with exit code {result.returncode}: {log}')

    # CellProfiler can log a Python error and still exit with 0. Treat that as a failure.
    if 'Traceback (most recent call last)' in log.read_text():
        raise ValueError(f'CellProfiler logged an exception: {log}')
    return metrics


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
        If a check of ``realign()`` or ``validate_analysis()`` fails.
    """
    corrections = realign(output, contract)
    qc = validate_analysis(output, rows, contract)
    qc['illumination'] = provenance
    qc['realigned'] = corrections

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


def run(args):
    """Run one illumination or analysis task and write its outputs under ``result/``.

    Parameters
    ----------
    args : argparse.Namespace
        The command-line arguments (see ``main()``).

    Raises
    ------
    ValueError
        If an input is wrong, CellProfiler fails, or a check fails.
    """
    rows = read_csv(args.manifest)
    if not rows or {r['Metadata_Plate'] for r in rows} != {args.plate}:
        raise ValueError('Task manifest must contain exactly its assigned plate')
    contract = json.loads(args.contract.read_text())
    logs = Path('result/logs')
    logs.mkdir(parents=True, exist_ok=True)
    output = Path('result/illumination') if args.kind == 'illumination' else Path('result/analysis') / args.batch
    output.mkdir(parents=True, exist_ok=True)
    provenance = {}
    if args.kind == 'analysis':
        if {r['Metadata_Batch'] for r in rows} != {args.batch}:
            raise ValueError('Task manifest has the wrong batch')
        provenance = add_illumination(rows, args.illumination, args.plate, contract)

    metrics = run_cellprofiler(args, rows, output, logs)
    if args.kind == 'illumination':
        check_illumination(output, rows, args.plate, contract)
    else:
        finish_analysis(output, rows, contract, provenance, logs, args.batch)
    write_csv(logs / f'{args.batch}.load_data.csv', rows)
    print(json.dumps(metrics))


def main():
    """Parse the arguments and run the task. Exit with code 2 and one line on a failed check."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('kind', choices=['illumination', 'analysis'])
    parser.add_argument('--plate', required=True)
    parser.add_argument('--batch', default='illumination')
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--pipeline', type=Path, required=True)
    parser.add_argument('--contract', type=Path, required=True)
    parser.add_argument('--plugins', type=Path, default=Path('plugins'))
    parser.add_argument('--illumination', type=Path)
    args = parser.parse_args()
    try:
        run(args)
    except (ValueError, FileNotFoundError, KeyError) as error:
        parser.exit(2, f'Task validation failed: {error}\n')


if __name__ == '__main__':
    main()
