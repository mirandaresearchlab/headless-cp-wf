#!/usr/bin/env python3
"""MERGE and CONCAT steps: build the per-cell feature table.

plate (MERGE, one task per plate)
  In:  the plate manifest, all batch folders of the plate (features/*.csv.gz) and contract.json.
  Out: <plate>.csv.gz with one row per cell. It stays in work/ and is not published.
all (CONCAT, one task)
  In:  every <plate>.csv.gz.
  Out: all_plates.csv.gz, the only published feature table. All plate tables must have the same columns.

File format: a CSV compressed with gzip, stored as two gzip parts ("members"). The first part
holds only the header line. The second part holds the rows. CONCAT checks each header, then
copies the compressed rows as they are, without unpacking them. gzip, zcat and pandas read the
result as one normal CSV.

How one cell row is built. The object names come from contract.json 'compartments':
  Cells row      the anchor. The output has one row per cell.
  Cytoplasm row  the same ObjectNumber as the cell. IdentifyTertiaryObjects keeps the number.
  Nuclei row     the nucleus whose Parent_Cells equals the cell number (set by RelateObjects).
  Image row      the image that holds the cell. Its values repeat on each cell row.
Columns: Metadata_* once, then Image_*, Cells_*, Cytoplasm_*, Nuclei_*.
Row order: plate image order (Metadata_PlateImageNumber), then cell number.
The values are copied as text. Nothing is rounded or calculated again.
"""
import argparse
import contextlib
import csv
import gzip
import io
import json
import shutil
from pathlib import Path

INDEX = 'Metadata_PlateImageNumber'

# Fastest gzip level. On these tables it compresses as well as level 6 (2.1x) and runs 4x faster.
LEVEL = 1
KEYS = ('ImageNumber', 'Metadata_Plate', 'Metadata_Batch', 'Metadata_Acquisition')


def header_member(columns):
    """Compress the header line on its own, as the first gzip part of a table.

    The result is the same bytes every time for the same columns. CONCAT uses this to find
    where the header ends and the rows start.

    Args:
        columns: the column names.

    Returns:
        The compressed header line as bytes.
    """
    text = io.StringIO()
    csv.writer(text).writerow(columns)
    return gzip.compress(text.getvalue().encode('utf-8'), compresslevel=LEVEL, mtime=0)


def read_table(path):
    """Read one compressed CellProfiler table.

    Args:
        path: a .csv.gz file from a batch folder, e.g. features/Cells.csv.gz.

    Returns:
        (header, rows): the column names, and a list of dicts with one dict per row.

    Raises:
        ValueError: if the file has no header or a row has the wrong number of values.
    """
    with gzip.open(path, 'rt', newline='', encoding='utf-8') as stream:
        reader = csv.reader(stream)
        header = next(reader, None)
        if header is None:
            raise ValueError(f'Feature table has no header: {path}')
        rows = list(reader)
    if any(len(row) != len(header) for row in rows):
        raise ValueError(f'Malformed row in {path}')
    return header, [dict(zip(header, row)) for row in rows]


def features(header):
    """Return the columns of a table that go into the per-cell row.

    Metadata_* columns are written once at the start of the row, so they are left out here.
    ImageNumber is left out too. It is written once as Metadata_ImageNumber.
    """
    return [c for c in header if c != 'ImageNumber' and not c.startswith('Metadata_')]


def merge_plate(plate, manifest, batches, compartments, out):
    """Join the batch tables of one plate into one table with one row per cell.

    The function reads one batch at a time, so memory use depends on the batch size only.

    Args:
        plate: the plate name.
        manifest: the plate manifest with all image sets in plate order.
        batches: the batch folders of the plate.
        compartments: the object names from contract.json, e.g. {"cells": "Cells", ...}.
        out: the .csv.gz file to write.

    Returns:
        A summary for merge.json: number of cells, cells without a nucleus or cytoplasm, and so on.

    Raises:
        ValueError: if a batch is missing or failed, the columns differ between batches, or the
            rows do not match the counts in Image.csv.
    """

    # The plate manifest gives the order of the image sets. Position 1 is the first image set.
    with Path(manifest).open(newline='') as stream:
        order = [row['Metadata_Acquisition'] for row in csv.DictReader(stream)]

    # Position in the plate manifest equals ImageNumber in a single-batch run.
    index = {acquisition: i for i, acquisition in enumerate(order, 1)}
    if not order or len(index) != len(order):
        raise ValueError(f'Plate manifest is empty or has duplicate acquisitions: {manifest}')
    batches = sorted(batches, key=lambda p: p.name)
    if not batches or len({b.name for b in batches}) != len(batches):
        raise ValueError('Require uniquely named batch folders')
    cells, cytoplasm, nuclei = compartments['cells'], compartments['cytoplasm'], compartments['nuclei']
    names = {'Image': 'Image', cells: 'Cells', cytoplasm: 'Cytoplasm', nuclei: 'Nuclei'}
    headers, columns, seen, last, images = {}, None, set(), (0, 0), []
    report = dict(plate=plate, batches=[b.name for b in batches], image_sets=len(order), cells=0,
                  cells_without_nucleus=0, cells_without_cytoplasm=0, nuclei_without_cell=0)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('wb') as raw, contextlib.ExitStack() as rows_member:
        writer = None
        for folder in batches:

            # Only use a batch that passed its checks in run_task.py.
            if not (folder / 'validation.json').exists():
                raise ValueError(f'Batch did not pass validation: {folder.name}')

            # Read the four tables of this batch. Their columns must be the same in every batch.
            tables = {}
            for table in names:
                header, rows = read_table(folder / 'features' / f'{table}.csv.gz')
                if table not in headers:
                    missing = [k for k in KEYS + (() if table == 'Image' else ('ObjectNumber',)) if k not in header]
                    if missing:
                        raise ValueError(f'{table}: missing key columns {missing}')
                    headers[table] = header
                elif header != headers[table]:
                    raise ValueError(f'{table}: columns differ in {folder.name}')
                for row in rows:
                    if row['Metadata_Plate'] != plate or row['Metadata_Batch'] != folder.name:
                        raise ValueError(f'{table}: row from another plate or batch in {folder.name}: {row["Metadata_Acquisition"]}')
                    if row['Metadata_Acquisition'] not in index:
                        raise ValueError(f'{table}: acquisition not in plate manifest: {row["Metadata_Acquisition"]}')
                tables[table] = rows

            # With the first batch, build the output columns and start the file with the header.
            if columns is None:
                image_header = headers['Image']
                metadata = [c for c in image_header if c.startswith('Metadata_')]
                columns = metadata + [INDEX, 'Metadata_ImageNumber', 'Metadata_ObjectNumber']
                columns += [f'{names[t]}_{c}' for t in names for c in features(headers[t])]
                if len(set(columns)) != len(columns):
                    raise ValueError('Per-cell column names collide')
                raw.write(header_member(columns))

                # Everything written from here on goes into the second gzip part: the rows.
                rows_gzip = rows_member.enter_context(gzip.GzipFile(fileobj=raw, mode='wb', compresslevel=LEVEL, mtime=0))
                writer = csv.writer(rows_member.enter_context(io.TextIOWrapper(rows_gzip, encoding='utf-8', newline='')))

            # Group the batch rows by ImageNumber. ImageNumber is unique only inside one batch.
            by_image = {}
            for table, rows in tables.items():
                for row in rows:
                    by_image.setdefault(row['ImageNumber'], {}).setdefault(table, []).append(row)
            for number, image_rows in by_image.items():
                if len(image_rows.get('Image', [])) != 1:
                    raise ValueError(f'ImageNumber {number} in {folder.name} has no single Image.csv row')

            # Go through the images in plate order.
            for number, image_rows in sorted(by_image.items(), key=lambda item: index[item[1]['Image'][0]['Metadata_Acquisition']]):
                image = image_rows['Image'][0]
                acquisition = image['Metadata_Acquisition']

                # Each object table must have exactly Count_<Object> rows for this image.
                for table in (cells, cytoplasm, nuclei):
                    rows = image_rows.get(table, [])
                    if any(r['Metadata_Acquisition'] != acquisition for r in rows):
                        raise ValueError(f'{table}: ImageNumber {number} in {folder.name} does not match Image.csv')
                    if len(rows) != float(image[f'Count_{table}']) or len({r['ObjectNumber'] for r in rows}) != len(rows):
                        raise ValueError(f'{table}: rows for {acquisition} disagree with Count_{table}')

                # Tertiary objects carry the number of the cell they were cut from.
                cyto = {r['ObjectNumber']: r for r in image_rows.get(cytoplasm, [])}

                # Find the nucleus of each cell through Parent_Cells. A cell may have at most one.
                nucleus = {}
                for r in image_rows.get(nuclei, []):
                    parent = str(int(float(r[f'Parent_{cells}'])))
                    if parent == '0':
                        report['nuclei_without_cell'] += 1
                    elif parent in nucleus:
                        raise ValueError(f'Cell {parent} in {acquisition} has several nuclei; one row per cell is ambiguous')
                    else:
                        nucleus[parent] = r

                # Write one row per cell, in cell number order.
                for cell in sorted(image_rows.get(cells, []), key=lambda r: int(r['ObjectNumber'])):
                    key = (index[acquisition], int(cell['ObjectNumber']))

                    # Batches are contiguous slices of the plate manifest. Anything else breaks the order.
                    if key in seen or key < last:
                        raise ValueError(f'Duplicate or out-of-order cell {key} in {folder.name}')
                    seen.add(key)
                    last = key
                    parts = {'Image': image, cells: cell, cytoplasm: cyto.get(cell['ObjectNumber']),
                             nuclei: nucleus.get(cell['ObjectNumber'])}
                    if parts[cytoplasm] and int(float(parts[cytoplasm][f'Parent_{cells}'])) not in (key[1], 0):
                        raise ValueError(f'Cytoplasm {cell["ObjectNumber"]} in {acquisition} belongs to another cell')
                    report['cells_without_cytoplasm'] += parts[cytoplasm] is None
                    report['cells_without_nucleus'] += parts[nuclei] is None
                    if f'Children_{nuclei}_Count' in cell and float(cell[f'Children_{nuclei}_Count']) != int(parts[nuclei] is not None):
                        raise ValueError(f'Cell {cell["ObjectNumber"]} in {acquisition}: nucleus count disagrees with Children_{nuclei}_Count')

                    # Metadata first, then Image_*, Cells_*, Cytoplasm_*, Nuclei_*. A missing part stays blank.
                    row = [image[c] for c in metadata] + [key[0], number, cell['ObjectNumber']]
                    for table in names:
                        part = parts[table]
                        row += [part[c] if part else '' for c in features(headers[table])]
                    writer.writerow(row)
                    report['cells'] += 1
            images += [rows['Image'][0]['Metadata_Acquisition'] for rows in by_image.values()]

    # Every image set of the plate must appear exactly once.
    if sorted(images) != sorted(order):
        raise ValueError(f'Per-cell table must cover every plate image set exactly once: {plate}')
    report['columns'] = len(columns)
    return report


def concatenate(paths, out):
    """Join the plate tables into one table, in plate name order.

    MERGE already checked every row. This function checks that all headers are the same,
    writes the header once, then copies the compressed rows of each plate as they are.

    Args:
        paths: the <plate>.csv.gz files from MERGE.
        out: the all_plates.csv.gz file to write.

    Returns:
        A summary for all_plates.merge.json: the plates, the number of columns, the file size.

    Raises:
        ValueError: if a table has different columns, or was not written by MERGE.
    """
    paths = sorted(paths, key=lambda p: p.name)
    if not paths or len({p.name for p in paths}) != len(paths):
        raise ValueError('Require uniquely named plate tables')
    header = None
    with out.open('wb') as target:
        for path in paths:

            # Read only the first line of the table: its header.
            with gzip.open(path, 'rt', newline='', encoding='utf-8') as source:
                columns = next(csv.reader(source), None)
            if header is None:
                header = columns
                target.write(header_member(header))
            elif columns != header:
                missing = [c for c in header if c not in columns]
                extra = [c for c in columns or [] if c not in header]
                raise ValueError(f'{path.name}: columns differ from {paths[0].name}; missing {missing[:5]}, '
                                 f'extra {extra[:5]}, same set but different order: {not missing and not extra}')

            # Skip the compressed header part, then copy the compressed rows unchanged.
            member = header_member(columns)
            with path.open('rb') as source:
                if source.read(len(member)) != member:
                    raise ValueError(f'{path.name}: header is not a separate gzip member (not written by MERGE)')
                shutil.copyfileobj(source, target, 16 * 1024 * 1024)
    return dict(plates=[p.name.split('.')[0] for p in paths], columns=len(header), bytes=out.stat().st_size)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    one = commands.add_parser('plate', help='Join one plate\'s batches into one row per cell')
    one.add_argument('--plate', required=True)
    one.add_argument('--manifest', type=Path, required=True)
    one.add_argument('--batches', type=Path, required=True)
    one.add_argument('--contract', type=Path, required=True)
    every = commands.add_parser('all', help='Concatenate plate tables with identical columns')
    every.add_argument('tables', type=Path, nargs='+')
    for command in (one, every):
        command.add_argument('--out', type=Path, required=True)
        command.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()

    # Exit code 2 with one clear line tells Nextflow and the user what went wrong.
    try:
        if args.command == 'plate':
            compartments = json.loads(args.contract.read_text())['compartments']
            report = merge_plate(args.plate, args.manifest, [p for p in args.batches.iterdir() if p.is_dir()],
                                 compartments, args.out)
        else:
            report = concatenate(args.tables, args.out)
    except (ValueError, FileNotFoundError, KeyError) as error:
        parser.exit(2, f'Feature merge failed: {error}\n')
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
