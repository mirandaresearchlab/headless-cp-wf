#!/usr/bin/env python3
"""ILLUMINATION and ANALYSIS steps: run one CellProfiler task, then check what it wrote.

illumination (one task per plate)
  In:  the plate manifest (all image sets of the plate) and the illumination pipeline.
  Out: result/illumination/Illum<Channel>.npy and provenance.json (plate and SHA-256 per file).
analysis (one task per batch)
  In:  the batch manifest, the analysis pipeline and the illumination folder of the same plate.
  Out: result/analysis/<batch>/features/*.csv.gz, validation.json, and result/masks/*.tiff.
Both write result/logs/<batch>.log, <batch>.metrics.json and <batch>.load_data.csv.

What happens to the data inside one analysis task:
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
import os
from pathlib import Path
import resource
import shutil
import subprocess
import time

import numpy as np
import tifffile

from prepare import write_csv


def read_csv(path):
    """Read a CSV file as a list of dicts, one dict per row."""
    with Path(path).open(newline='') as stream:
        return list(csv.DictReader(stream))


def checksum(path):
    """Return the SHA-256 checksum of a file as text.

    The workflow uses it to prove that a batch read the correction files of its own plate.
    """
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# CP 4.2.8.1 MeasureObjectSizeShape (regionprops) and MeasureTexture (numpy.unique) compute these
# for labels that have pixels, then store them by position. An object without pixels, such as a
# cytoplasm fully covered by its nucleus, shifts every later object's values by one row.
# Zernike, Feret and all other modules index by object number and stay aligned.
SHIFTED = {'AreaShape_' + f for f in (
    'Area', 'Perimeter', 'MajorAxisLength', 'MinorAxisLength', 'Eccentricity', 'Orientation', 'Center_X',
    'Center_Y', 'BoundingBoxArea', 'BoundingBoxMinimum_X', 'BoundingBoxMaximum_X', 'BoundingBoxMinimum_Y',
    'BoundingBoxMaximum_Y', 'FormFactor', 'Extent', 'Solidity', 'Compactness', 'EulerNumber',
    'MaximumRadius', 'MeanRadius', 'MedianRadius', 'ConvexArea', 'EquivalentDiameter')}
SHIFTED_PREFIXES = ('Texture_', 'AreaShape_SpatialMoment_', 'AreaShape_CentralMoment_', 'AreaShape_NormalizedMoment_',
                    'AreaShape_HuMoment_', 'AreaShape_InertiaTensor')

# Radii are preallocated with zeros, so their unused tail is 0.0 instead of nan.
ZERO_PADDED = {'AreaShape_MaximumRadius', 'AreaShape_MeanRadius', 'AreaShape_MedianRadius'}


def realign(output, contract):
    """Move shifted CellProfiler values back to the objects they belong to.

    CellProfiler 4.2.8.1 writes some shape and texture values one row too early after an
    object that has no pixels (see SHIFTED above). This function moves them back. Objects
    without pixels get nan. A table is rewritten only if one of its images needs a correction.

    Args:
        output: the batch folder with features/ and mask_manifest.csv.
        contract: the contract from PREPARE. It lists the object types.

    Returns:
        A list of corrections, one per image and object type, for validation.json.

    Raises:
        ValueError: if the values do not show the known shift pattern. Then the cause is
            something else, and the data must not be changed.
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

        # Only the shifted columns move. All other columns are already correct.
        shifted = [i for name, i in col.items() if name in SHIFTED or name.startswith(SHIFTED_PREFIXES)]
        if not shifted:
            continue
        for mask in (m for m in masks if m['ObjectType'] == obj):

            # The rows of this image, sorted by object number. The numbers must run 1, 2, ..., N.
            image = sorted((r for r in table if r[col['ImageNumber']] == mask['ImageNumber']),
                           key=lambda r: int(r[col['ObjectNumber']]))
            if [int(r[col['ObjectNumber']]) for r in image] != list(range(1, len(image) + 1)):
                raise ValueError(f'{obj}: object numbers are not 1..N in image {mask["ImageNumber"]}')

            # Count the pixels of each object in the mask. An object with 0 pixels is empty.
            pixels = np.bincount(tifffile.imread(output / mask['MaskPath']).ravel(), minlength=len(image) + 1)[1:]
            if len(pixels) != len(image):
                raise ValueError(f'{obj}: mask labels exceed measurement rows in image {mask["ImageNumber"]}')
            present = np.flatnonzero(pixels)
            if len(present) == len(image):
                continue
            for i in shifted:

                # Known pattern: the last rows hold no value (nan, or 0.0 for the radii).
                pad = '0.0' if header[i] in ZERO_PADDED else 'nan'
                if {r[i] for r in image[len(present):]} != {pad}:
                    raise ValueError(f'{obj}: {header[i]} does not show the known CP 4.2.8.1 shift; review before use')

                # The first values belong to the objects that have pixels, in order.
                values = [r[i] for r in image[:len(present)]]
                for r in image:
                    r[i] = 'nan'
                for j, value in zip(present, values):
                    image[j][i] = value
            corrections.append(dict(object=obj, image_number=mask['ImageNumber'], acquisition=mask['Acquisition'],
                                    empty_objects=[int(j) + 1 for j in np.flatnonzero(pixels == 0)], columns=len(shifted)))

        # Write the table back only if something moved. The row order stays the same.
        if any(c['object'] == obj for c in corrections):
            with path.open('w', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow(header)
                writer.writerows(table)
    return corrections


def validate_analysis(output, rows, contract):
    """Check the tables and masks of one batch against its manifest.

    Checks:
      - Image.csv has exactly the image sets of the manifest.
      - Each image set has one mask per object type. The mask names its image set and
        exactly the files that this batch loaded for it.
      - Object numbers run 1..N, and N equals Count_<Object> in Image.csv.
      - Each mask label has a row. A row can have no pixels (an empty object).
      - AreaShape_Area equals the pixel count of the object in its mask.
        AreaShape_Center_X equals Location_Center_X. Together these prove that every row
        belongs to the right object.

    Args:
        output: the batch folder with features/, masks/ and mask_manifest.csv.
        rows: the manifest rows of this batch, including the illumination file names.
        contract: the contract from PREPARE.

    Returns:
        A summary for validation.json: image sets, masks, object types, empty objects.

    Raises:
        ValueError: on the first check that fails.
    """

    # The exported image sets must be exactly the ones in the manifest.
    images = read_csv(output / 'features' / 'Image.csv')
    key = lambda r: tuple(r['Metadata_' + k] for k in ('Plate', 'Batch', 'Acquisition'))
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
    by_acquisition = {r['Metadata_Acquisition']: r for r in rows}
    tables, empty = {}, {}
    for obj in contract['objects']:
        tables[obj] = read_csv(output / 'features' / f'{obj}.csv')
    for row in masks:
        obj, number = row['ObjectType'], row['ImageNumber']
        im = image_by_number[number]
        if (row['Plate'], row['Batch'], row['Acquisition']) != key(im):
            raise ValueError(f'Mask/image acquisition mismatch: {row}')
        with tifffile.TiffFile(output / row['MaskPath']) as tiff:
            labels = tiff.asarray()
            provenance = json.loads(tiff.pages[0].description)
        if labels.dtype != np.uint32 or labels.ndim != 2:
            raise ValueError(f'Mask is not a uint32 label image: {row}')

        # The mask must name its own image set and exactly the files this batch loaded for it.
        loaded = by_acquisition[row['Acquisition']]
        if provenance['object'] != obj or {k: provenance['metadata'][k] for k in ('Plate', 'Batch', 'Acquisition')} != \
                dict(Plate=row['Plate'], Batch=row['Batch'], Acquisition=row['Acquisition']) or not provenance['source_files'] or \
                any((loaded['FileName_' + n], loaded['PathName_' + n]) != (f['file'], f['folder']) for n, f in provenance['source_files'].items()):
            raise ValueError(f'Mask provenance does not match its image set: {row["MaskPath"]}')

        # Compare the rows of this image with the labels in its mask.
        objects = [r for r in tables[obj] if r['ImageNumber'] == number]
        ids = [int(r['ObjectNumber']) for r in objects]
        pixels = np.bincount(labels.ravel(), minlength=len(ids) + 1)
        present = set(np.flatnonzero(pixels)) - {0}

        # Objects without pixels keep their rows and numbers (e.g. cytoplasm covered by its nucleus).
        if sorted(ids) != list(range(1, len(ids) + 1)) or not present <= set(ids) or len(ids) != float(im['Count_' + obj]):
            raise ValueError(f'Mask labels, measurement rows and count disagree: {obj}, image {number}')
        if len(present) != int(row['LabelCount']):
            raise ValueError(f'Mask manifest label count disagrees: {row}')
        empty[obj] = empty.get(obj, 0) + len(ids) - len(present)
        for r in objects:
            n = int(r['ObjectNumber'])

            # Independent proof that every object's shape row belongs to its label.
            if 'AreaShape_Area' in r and not (float(r['AreaShape_Area']) == pixels[n] if pixels[n] else r['AreaShape_Area'] == 'nan'):
                raise ValueError(f'{obj}: AreaShape_Area does not match mask pixels for object {n}, image {number}')
            if 'AreaShape_Center_X' in r and 'Location_Center_X' in r and not np.isclose(
                    float(r['AreaShape_Center_X']), float(r['Location_Center_X']), rtol=0, atol=1e-6, equal_nan=True):
                raise ValueError(f'{obj}: AreaShape_Center_X disagrees with Location_Center_X for object {n}, image {number}')
    return {'image_sets': len(images), 'masks': len(masks), 'objects': contract['objects'], 'empty_objects': empty}


def run(args):
    """Run one illumination or analysis task and write its outputs under result/.

    Args:
        args: the command-line arguments (see the bottom of this file).

    Raises:
        ValueError: if an input is wrong, CellProfiler fails, or a check fails.
    """

    # The manifest must hold only this task's plate.
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

        # Use only correction files that belong to this plate and have the recorded checksum.
        saved = json.loads((args.illumination / 'provenance.json').read_text())
        if saved['plate'] != args.plate:
            raise ValueError('Illumination plate does not match analysis plate')
        for name in contract['corrections']:
            function = (args.illumination / (name + '.npy')).resolve()
            if checksum(function) != saved['sha256'][name]:
                raise ValueError(f'Illumination checksum mismatch: {function}')
            provenance[name] = {'plate': args.plate, 'sha256': saved['sha256'][name]}

            # LoadData reads the correction file like an image: it needs a file name and a folder.
            for row in rows:
                row['FileName_' + name] = function.name
                row['PathName_' + name] = str(function.parent)

    # Run CellProfiler headless on this task's manifest. Its log goes to result/logs/.
    write_csv(Path('load_data.csv'), rows)
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

    # Record time and peak memory. The README speed advice comes from these numbers.
    elapsed = time.monotonic() - start
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    metrics = dict(plate=args.plate, batch=args.batch, kind=args.kind, elapsed_seconds=elapsed,
                   peak_rss_kib=usage.ru_maxrss, image_sets=len(rows),
                   sets_per_minute=60 * len(rows) / elapsed, exit_code=result.returncode)
    (logs / f'{args.batch}.metrics.json').write_text(json.dumps(metrics, indent=2))
    if result.returncode:
        print(log.read_text()[-8000:])
        raise ValueError(f'CellProfiler failed with exit code {result.returncode}: {log}')

    # CellProfiler can log a Python error and still exit with 0. Treat that as a failure.
    if 'Traceback (most recent call last)' in log.read_text():
        raise ValueError(f'CellProfiler logged an exception: {log}')
    if args.kind == 'illumination':

        # Exactly the expected .npy files, each the size of the images, finite and above 0.
        expected_files = {name + '.npy' for name in contract['calculated']}
        if {p.name for p in output.glob('*.npy')} != expected_files:
            raise ValueError('Illumination output functions differ from the pipeline contract')
        sums = {}
        for name, image in contract['calculated'].items():
            path = output / (name + '.npy')
            function = np.load(path, allow_pickle=False)
            source = Path(rows[0]['PathName_' + image]) / rows[0]['FileName_' + image]
            with tifffile.TiffFile(source) as tiff:
                shape = tiff.series[0].shape
            if function.shape != shape or not np.isfinite(function).all() or np.min(function) <= 0:
                raise ValueError(f'Invalid plate correction function: {path}')
            sums[name] = checksum(path)

        # The analysis batches check these checksums before they use the files.
        (output / 'provenance.json').write_text(json.dumps(dict(plate=args.plate, image_sets=len(rows), sha256=sums), indent=2))
    else:
        corrections = realign(output, contract)
        qc = validate_analysis(output, rows, contract)
        qc['illumination'] = provenance
        qc['realigned'] = corrections

        # Compress the checked tables. MERGE reads them as .csv.gz. This halves the space in work/.
        for table in (output / 'features').glob('*.csv'):
            with table.open('rb') as source, gzip.open(table.with_suffix('.csv.gz'), 'wb', compresslevel=1) as target:
                shutil.copyfileobj(source, target)
            table.unlink()

        # MERGE only uses a batch that has validation.json, so write it last.
        for path in (output / 'validation.json', logs / f'{args.batch}.validation.json'):
            path.write_text(json.dumps(qc, indent=2))

        # Nextflow does not publish files nested inside another output folder, so masks sit beside it.
        (output / 'masks').rename(Path('result/masks'))
    write_csv(logs / f'{args.batch}.load_data.csv', rows)
    print(json.dumps(metrics))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=['illumination', 'analysis'])
    parser.add_argument('--plate', required=True)
    parser.add_argument('--batch', default='illumination')
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--pipeline', type=Path, required=True)
    parser.add_argument('--contract', type=Path, required=True)
    parser.add_argument('--plugins', type=Path, default=Path('plugins'))
    parser.add_argument('--illumination', type=Path)
    args = parser.parse_args()

    # Exit code 2 with one clear line tells Nextflow and the user what went wrong.
    try:
        run(args)
    except (ValueError, FileNotFoundError, KeyError) as error:
        parser.exit(2, f'Task validation failed: {error}\n')
