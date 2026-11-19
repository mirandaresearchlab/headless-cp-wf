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

from cp_inputs import read_csv

INDEX = 'Metadata_PlateImageNumber'

# Fastest gzip level. On these tables it compresses as well as level 6 (2.1x) and runs 4x faster.
LEVEL = 1

# Columns that every exported table needs to place its rows. Object tables also need ObjectNumber.
KEYS = ('ImageNumber', 'Metadata_Plate', 'Metadata_Batch', 'Metadata_Acquisition')


def header_member(columns):
    """Compress the header line on its own, as the first gzip part of a table.

    The result is the same bytes every time for the same columns. CONCAT uses this to find
    where the header ends and the rows start.

    Parameters
    ----------
    columns : list of str
        The column names.

    Returns
    -------
    bytes
        The compressed header line.
    """
    text = io.StringIO()
    csv.writer(text).writerow(columns)
    return gzip.compress(text.getvalue().encode('utf-8'), compresslevel=LEVEL, mtime=0)


def read_table(path):
    """Read one compressed CellProfiler table.

    Parameters
    ----------
    path : Path
        A ``.csv.gz`` file from a batch folder, e.g. ``features/Cells.csv.gz``.

    Returns
    -------
    header : list of str
        The column names.
    rows : list of dict
        One dict per row.

    Raises
    ------
    ValueError
        If the file has no header or a row has the wrong number of values.
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

    Metadata_* columns are written once at the start of the row, and ImageNumber once as
    Metadata_ImageNumber, so both are left out here.

    Parameters
    ----------
    header : list of str
        The columns of one exported table.

    Returns
    -------
    list of str
        The feature columns.
    """
    return [c for c in header if c != 'ImageNumber' and not c.startswith('Metadata_')]


def read_batch(folder, tables, headers, plate, index):
    """Read and check the tables of one batch, grouped by image.

    Parameters
    ----------
    folder : Path
        The batch folder, with ``features/<table>.csv.gz`` and ``validation.json``.
    tables : list of str
        The table names: ``Image`` and the three cell compartments.
    headers : dict
        Table name -> columns, from the first batch. Filled in by the first call.
    plate : str
        The plate of this MERGE task.
    index : dict
        Acquisition -> position in the plate manifest (1, 2, ...).

    Returns
    -------
    dict
        ImageNumber -> {table name: list of rows}. ImageNumber is unique only inside one batch.

    Raises
    ------
    ValueError
        If the batch did not pass its checks, a key column is missing, the columns differ from
        the first batch, a row belongs to another plate or batch, or an image has not exactly
        one Image row.
    """
    # Only use a batch that passed its checks in run_task.py.
    if not (folder / 'validation.json').exists():
        raise ValueError(f'Batch did not pass validation: {folder.name}')
    by_image = {}
    for table in tables:
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
            by_image.setdefault(row['ImageNumber'], {}).setdefault(table, []).append(row)
    for number, image_rows in by_image.items():
        if len(image_rows.get('Image', [])) != 1:
            raise ValueError(f'ImageNumber {number} in {folder.name} has no single Image.csv row')
    return by_image


def cells_of_image(image_rows, compartments, report):
    """Join the cytoplasm and the nucleus of each cell in one image.

    Parameters
    ----------
    image_rows : dict
        Table name -> rows of one image, from ``read_batch()``.
    compartments : dict
        The object names from contract.json: ``cells``, ``cytoplasm`` and ``nuclei``.
    report : dict
        The MERGE summary. The counts of cells without a part are added here.

    Yields
    ------
    tuple
        (cell row, cytoplasm row or None, nucleus row or None), in cell number order.

    Raises
    ------
    ValueError
        If an object table disagrees with ``Count_<Object>`` in the Image row, a cell has
        several nuclei, a cytoplasm belongs to another cell, or the nucleus count of a cell
        disagrees with ``Children_<Nuclei>_Count``.
    """
    cells, cytoplasm, nuclei = compartments['cells'], compartments['cytoplasm'], compartments['nuclei']
    image = image_rows['Image'][0]
    acquisition = image['Metadata_Acquisition']

    # Each object table must have exactly Count_<Object> rows, with unique numbers.
    for part, table in (('Cells', cells), ('Cytoplasm', cytoplasm), ('Nuclei', nuclei)):
        rows = image_rows.get(table, [])
        if any(r['Metadata_Acquisition'] != acquisition for r in rows):
            raise ValueError(f'{table}: ImageNumber {image["ImageNumber"]} does not match Image.csv')
        if len(rows) != float(image[f'Count_{table}']) or len({r['ObjectNumber'] for r in rows}) != len(rows):
            raise ValueError(f'{table}: rows for {acquisition} disagree with Count_{table}')
        report['objects'][part] += len(rows)

    # IdentifyTertiaryObjects gives a cytoplasm the number of the cell it was cut from.
    # Every cytoplasm and every nucleus must find its cell, or the table would lose its row.
    numbers = {r['ObjectNumber'] for r in image_rows.get(cells, [])}
    cyto = {r['ObjectNumber']: r for r in image_rows.get(cytoplasm, [])}
    if set(cyto) - numbers:
        raise ValueError(f'Cytoplasm {sorted(set(cyto) - numbers)} in {acquisition} has no cell with the same number')

    # RelateObjects gives a nucleus the number of its cell in Parent_<Cells>. 0 means no cell.
    nucleus = {}
    for r in image_rows.get(nuclei, []):
        parent = str(int(float(r[f'Parent_{cells}'])))
        if parent == '0':
            report['nuclei_without_cell'] += 1
        elif parent not in numbers:
            raise ValueError(f'Nucleus {r["ObjectNumber"]} in {acquisition} names cell {parent}, but there is no cell {parent}')
        elif parent in nucleus:
            raise ValueError(f'Cell {parent} in {acquisition} has several nuclei; one row per cell is ambiguous')
        else:
            nucleus[parent] = r

    for cell in sorted(image_rows.get(cells, []), key=lambda r: int(r['ObjectNumber'])):
        number = cell['ObjectNumber']
        part_cyto, part_nucleus = cyto.get(number), nucleus.get(number)
        if part_cyto and int(float(part_cyto[f'Parent_{cells}'])) not in (int(number), 0):
            raise ValueError(f'Cytoplasm {number} in {acquisition} belongs to another cell')
        if f'Children_{nuclei}_Count' in cell and float(cell[f'Children_{nuclei}_Count']) != int(part_nucleus is not None):
            raise ValueError(f'Cell {number} in {acquisition}: nucleus count disagrees with Children_{nuclei}_Count')
        report['cells_without_cytoplasm'] += part_cyto is None
        report['cells_without_nucleus'] += part_nucleus is None
        yield cell, part_cyto, part_nucleus


def merge_plate(plate, manifest, batches, compartments, out):
    """Join the batch tables of one plate into one table with one row per cell.

    The function reads one batch at a time, so its memory use depends on the batch size only.

    Parameters
    ----------
    plate : str
        The plate name.
    manifest : Path
        The plate manifest with all image sets in plate order.
    batches : list of Path
        The batch folders of the plate.
    compartments : dict
        The object names from contract.json, e.g. ``{"cells": "Cells", ...}``.
    out : Path
        The ``.csv.gz`` file to write.

    Returns
    -------
    dict
        A summary for merge.json: number of cells, cells without a nucleus or cytoplasm, etc.

    Raises
    ------
    ValueError
        If a batch is missing or failed, the columns differ between batches, the rows disagree
        with the counts in Image.csv, or the image sets are not each in the table exactly once.
    """
    # Position in the plate manifest gives the plate image order. Position 1 is the first image set.
    order = [row['Metadata_Acquisition'] for row in read_csv(manifest)]
    index = {acquisition: i for i, acquisition in enumerate(order, 1)}
    if not order or len(index) != len(order):
        raise ValueError(f'Plate manifest is empty or has duplicate acquisitions: {manifest}')
    batches = sorted(batches, key=lambda p: p.name)
    if not batches or len({b.name for b in batches}) != len(batches):
        raise ValueError('Require uniquely named batch folders')

    # Exported table name -> the prefix of its columns in the per-cell table.
    names = {'Image': 'Image', compartments['cells']: 'Cells', compartments['cytoplasm']: 'Cytoplasm', compartments['nuclei']: 'Nuclei'}
    headers, columns, last, images = {}, None, (0, 0), []
    report = dict(
        plate=plate,
        batches=[b.name for b in batches],
        image_sets=len(order),
        cells=0,
        cells_without_nucleus=0,
        cells_without_cytoplasm=0,
        nuclei_without_cell=0,
        objects=dict(Cells=0, Cytoplasm=0, Nuclei=0),
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('wb') as raw, contextlib.ExitStack() as rows_member:
        writer = None
        for folder in batches:
            by_image = read_batch(folder, list(names), headers, plate, index)

            # With the first batch, build the output columns and write the header as its own gzip part.
            if columns is None:
                metadata = [c for c in headers['Image'] if c.startswith('Metadata_')]
                columns = metadata + [INDEX, 'Metadata_ImageNumber', 'Metadata_ObjectNumber']
                columns += [f'{names[t]}_{c}' for t in names for c in features(headers[t])]
                if len(set(columns)) != len(columns):
                    raise ValueError('Per-cell column names collide')
                raw.write(header_member(columns))

                # Everything written from here on goes into the second gzip part: the rows.
                rows_gzip = rows_member.enter_context(gzip.GzipFile(fileobj=raw, mode='wb', compresslevel=LEVEL, mtime=0))
                writer = csv.writer(rows_member.enter_context(io.TextIOWrapper(rows_gzip, encoding='utf-8', newline='')))

            # Go through the images in plate order, then the cells in cell number order.
            for number, image_rows in sorted(by_image.items(), key=lambda item: index[item[1]['Image'][0]['Metadata_Acquisition']]):
                image = image_rows['Image'][0]
                for cell, part_cyto, part_nucleus in cells_of_image(image_rows, compartments, report):
                    # Batches are consecutive slices of the plate manifest, so the key must always
                    # increase. A repeated or smaller key means a duplicate or a wrong batch order.
                    key = (index[image['Metadata_Acquisition']], int(cell['ObjectNumber']))
                    if key <= last:
                        raise ValueError(f'Duplicate or out-of-order cell {key} in {folder.name}')
                    last = key

                    # Metadata first, then Image_*, Cells_*, Cytoplasm_*, Nuclei_*. A missing part stays blank.
                    parts = {
                        'Image': image,
                        compartments['cells']: cell,
                        compartments['cytoplasm']: part_cyto,
                        compartments['nuclei']: part_nucleus,
                    }
                    row = [image[c] for c in metadata] + [key[0], number, cell['ObjectNumber']]
                    for table in names:
                        row += [parts[table][c] if parts[table] else '' for c in features(headers[table])]
                    writer.writerow(row)
                    report['cells'] += 1
            images += [rows['Image'][0]['Metadata_Acquisition'] for rows in by_image.values()]

    # Every image set of the plate must appear exactly once.
    if sorted(images) != sorted(order):
        raise ValueError(f'Per-cell table must cover every plate image set exactly once: {plate}')

    # Every object of the plate is in the table once, or is counted as not joined. So the row
    # count can only be the number of cells: no object is lost and no row is repeated.
    objects = report['objects']
    if (
        report['cells'] != objects['Cells']
        or report['cells'] - report['cells_without_nucleus'] + report['nuclei_without_cell'] != objects['Nuclei']
        or report['cells'] - report['cells_without_cytoplasm'] != objects['Cytoplasm']
    ):
        raise ValueError(f'Object accounting failed for plate {plate}: {report}')
    report['columns'] = len(columns)
    return report


def concatenate(paths, out):
    """Join the plate tables into one table, in plate name order.

    MERGE already checked every row. This function checks that all headers are the same,
    writes the header once, then copies the compressed rows of each plate as they are.

    Parameters
    ----------
    paths : list of Path
        The ``<plate>.csv.gz`` files from MERGE.
    out : Path
        The ``all_plates.csv.gz`` file to write.

    Returns
    -------
    dict
        A summary for all_plates.merge.json: the plates, the number of columns, the file size.

    Raises
    ------
    ValueError
        If a table has different columns, or was not written by MERGE.
    """
    paths = sorted(paths, key=lambda p: p.name)
    if not paths or len({p.name for p in paths}) != len(paths):
        raise ValueError('Require uniquely named plate tables')
    header = None
    with out.open('wb') as target:
        for path in paths:
            with gzip.open(path, 'rt', newline='', encoding='utf-8') as source:
                columns = next(csv.reader(source), None)
            if header is None:
                header = columns
                target.write(header_member(header))
            elif columns != header:
                missing = [c for c in header if c not in columns]
                extra = [c for c in columns or [] if c not in header]
                raise ValueError(
                    f'{path.name}: columns differ from {paths[0].name}; missing {missing[:5]}, '
                    f'extra {extra[:5]}, same set but different order: {not missing and not extra}'
                )

            # Skip the compressed header part, then copy the compressed rows unchanged.
            member = header_member(columns)
            with path.open('rb') as source:
                if source.read(len(member)) != member:
                    raise ValueError(f'{path.name}: header is not a separate gzip member (not written by MERGE)')
                shutil.copyfileobj(source, target, 16 * 1024 * 1024)
    return dict(plates=[p.name.split('.')[0] for p in paths], columns=len(header), bytes=out.stat().st_size)


def main():
    """Parse the arguments and run MERGE (``plate``) or CONCAT (``all``). Exit with code 2 on an error."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    plate = commands.add_parser('plate', help="Join one plate's batches into one row per cell")
    plate.add_argument('--plate', required=True)
    plate.add_argument('--manifest', type=Path, required=True)
    plate.add_argument('--batches', type=Path, required=True)
    plate.add_argument('--contract', type=Path, required=True)
    every = commands.add_parser('all', help='Concatenate plate tables with identical columns')
    every.add_argument('tables', type=Path, nargs='+')
    for command in (plate, every):
        command.add_argument('--out', type=Path, required=True)
        command.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'plate':
            compartments = json.loads(args.contract.read_text())['compartments']
            report = merge_plate(args.plate, args.manifest, [p for p in args.batches.iterdir() if p.is_dir()], compartments, args.out)
        else:
            report = concatenate(args.tables, args.out)
    except (ValueError, FileNotFoundError, KeyError) as error:
        parser.exit(2, f'Feature merge failed: {error}\n')
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
