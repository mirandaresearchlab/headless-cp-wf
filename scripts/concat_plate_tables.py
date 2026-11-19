#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["duckdb==1.4.1"]
# ///
"""Join the per-plate cell tables of a plate-by-plate run into one Parquet table.

    uv run --python 3.12 scripts/concat_plate_tables.py <results> [--out <path>] [--per-plate]

<results> is the OUT folder of scripts/berzelius-run-plates.sbatch. It has one folder per plate.
Each finished plate has a DONE file. The DONE file holds the path of the results of that plate.
The script reads cp_features/all_plates.csv.gz of every plate. It writes one Parquet file with
one row per cell, in plate name order (default: <results>/all_plates.parquet). With --per-plate,
it writes one Parquet file per plate into a folder (default: <results>/parquet). The files have
the same columns and types, so they also read as one table.

DuckDB streams the CSV into the Parquet file, so the table is never held in memory. The column
types are fixed, not guessed: text for metadata and file names, integers for image and object
numbers, and doubles for all measurements. Every missing value (empty, nan, inf) becomes a
Parquet null. A value that is not a number or a missing-value token stops the conversion.

The script stops before it writes anything if a plate has no DONE file, if the output exists,
or if the plates have different columns. It writes to <output>.partial and renames the file
only after these checks pass:
  - the rows of each plate equal the cell count in the MERGE report of that plate
  - the columns, and their order, equal the CSV header
  - the rows are in MERGE order: plate, then Metadata_PlateImageNumber, then Metadata_ObjectNumber,
    and no cell occurs twice
  - each plate has the same rows, with the same values, as its CSV (a hash of every full row)
  - the parts of each row belong to one cell: Cells_ObjectNumber, Cytoplasm_ObjectNumber,
    Cytoplasm_Parent_Cells and Nuclei_Parent_Cells point to the cell of the row, and each image
    has Image_Count_Cells rows
  - no NaN or infinite value is left in a measurement column
The order and value checks read the CSV a second time, so they make the job take longer.
The report also counts rows whose nucleus centre or cytoplasm lies outside the cell bounding box.
These counts are only warnings.
The plate tables stay where they are. Next to the output, the script writes <name>.null_counts.csv
(the nulls per column), and one report: <name>.report.json, or report.json in the --per-plate folder.

Run it as a Slurm job, not on the login node: scripts/berzelius-concat-parquet.sbatch.
"""

import argparse
import csv
import gzip
import json
import shutil
import sys
from pathlib import Path

import duckdb

TABLE = Path('cp_features') / 'all_plates.csv.gz'

# Every missing-value token in the CSV becomes a Parquet null.
# nan and inf come from CellProfiler. An empty field is a Cytoplasm column of a cell without a cytoplasm.
NULL_TOKENS = ['', 'nan', 'NaN', '-nan', 'inf', '-inf', 'Inf', '-Inf', 'Infinity', '-Infinity']
TEXT_PREFIXES = ('Metadata_', 'Image_FileName_', 'Image_PathName_', 'Image_URL_', 'Image_MD5Digest_')
INTEGER_METADATA = {
    'Metadata_Site',
    'Metadata_X',
    'Metadata_Y',
    'Metadata_PlateImageNumber',
    'Metadata_ImageNumber',
    'Metadata_ObjectNumber',
}

# Rows per Parquet row group. About 4,000 columns x 10,000 rows x 8 bytes = 320 MB for each writer.
ROW_GROUP_SIZE = 10_000


def plate_tables(results):
    """Find the table and the expected cell count of every plate.

    Parameters
    ----------
    results : Path
        The folder with one sub-folder per plate.

    Returns
    -------
    list of tuple
        (plate name, table path, cells), sorted by plate name.

    Raises
    ------
    ValueError
        If there is no plate, a plate has no DONE file, or a table or report is missing.
    """
    plates = sorted(p for p in results.iterdir() if p.is_dir() and not p.name.startswith('.') and p.name != 'parquet')
    if not plates:
        raise ValueError(f'No plate folders in {results}')
    missing = [p.name for p in plates if not (p / 'DONE').is_file()]
    if missing:
        raise ValueError(f'No DONE file for: {", ".join(missing)}. Their runs are not complete.')
    tables = []
    for plate in plates:
        run = Path((plate / 'DONE').read_text().strip())
        table = run / TABLE
        if not table.is_file() or table.stat().st_size == 0:
            raise ValueError(f'{plate.name}: table missing or empty: {table}')
        report = run / 'logs' / plate.name / 'merge.json'
        if not report.is_file():
            raise ValueError(f'{plate.name}: MERGE report missing: {report}')
        tables.append((plate.name, table, json.loads(report.read_text())['cells']))
    return tables


def read_header(path):
    """Read only the header line of a gzip CSV file.

    Parameters
    ----------
    path : Path
        The ``.csv.gz`` file.

    Returns
    -------
    list of str
        The column names.
    """
    with gzip.open(path, 'rt', newline='', encoding='utf-8') as stream:
        return next(csv.reader(stream))


def column_type(name):
    """Return the DuckDB type of one column of the per-cell table.

    Parameters
    ----------
    name : str
        The column name.

    Returns
    -------
    str
        ``BIGINT`` for image and object numbers, ``VARCHAR`` for metadata and file names,
        ``DOUBLE`` for all measurements.
    """
    if name in INTEGER_METADATA:
        return 'BIGINT'
    if name.startswith(TEXT_PREFIXES):
        return 'VARCHAR'
    return 'DOUBLE'


def sql_text(value):
    """Quote one string for SQL.

    Parameters
    ----------
    value : str
        The text.

    Returns
    -------
    str
        The text in single quotes, with each single quote doubled.
    """
    return "'" + value.replace("'", "''") + "'"


def read_csv_sql(sources, schema):
    """Return the DuckDB ``read_csv`` call for gzip CSV files, with fixed column types and null tokens.

    Parameters
    ----------
    sources : list of Path
        The ``.csv.gz`` files, read in this order.
    schema : dict
        Column -> DuckDB type.

    Returns
    -------
    str
        The SQL table expression.
    """
    columns = '{' + ', '.join(f'{sql_text(name)}: {sql_text(dtype)}' for name, dtype in schema.items()) + '}'
    files = '[' + ', '.join(sql_text(str(path)) for path in sources) + ']'
    nulls = '[' + ', '.join(sql_text(token) for token in NULL_TOKENS) + ']'
    return f"read_csv({files}, compression = 'gzip', header = true, auto_detect = false, columns = {columns}, nullstr = {nulls})"


def convert(con, sources, target, schema):
    """Stream one or more gzip CSV files, in order, into one Parquet file.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        The DuckDB connection.
    sources : list of Path
        The ``.csv.gz`` files, in output order.
    target : Path
        The Parquet file to write.
    schema : dict
        Column -> DuckDB type.
    """
    con.execute(f"""
        COPY (SELECT * FROM {read_csv_sql(sources, schema)})
        TO {sql_text(str(target))} (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE {ROW_GROUP_SIZE})
    """)


# Each check counts the rows where the parts of one row do not describe the same cell.
# The Metadata_ObjectNumber of a row is the number of its cell. A check runs only if its columns exist.
# Cytoplasm_Parent_Cells may be 0: CellProfiler gives 0 when the cytoplasm has no parent.
IDENTITY = [
    # (what is wrong, columns needed, SQL condition that is true for a wrong row)
    (
        'Cells_ObjectNumber differs from the cell number',
        ('Cells_ObjectNumber',),
        'Cells_ObjectNumber IS DISTINCT FROM Metadata_ObjectNumber',
    ),
    (
        'Cells_Number_Object_Number differs from the cell number',
        ('Cells_Number_Object_Number',),
        'Cells_Number_Object_Number IS DISTINCT FROM Metadata_ObjectNumber',
    ),
    ('Cytoplasm_ObjectNumber differs from the cell number', ('Cytoplasm_ObjectNumber',), 'Cytoplasm_ObjectNumber <> Metadata_ObjectNumber'),
    ('Cytoplasm_Parent_Cells is another cell', ('Cytoplasm_Parent_Cells',), 'Cytoplasm_Parent_Cells NOT IN (Metadata_ObjectNumber, 0)'),
    ('Nuclei_Parent_Cells is another cell', ('Nuclei_Parent_Cells',), 'Nuclei_Parent_Cells <> Metadata_ObjectNumber'),
    (
        'Cells_Children_Nuclei_Count disagrees with the nucleus columns',
        ('Cells_Children_Nuclei_Count', 'Nuclei_ObjectNumber'),
        'Cells_Children_Nuclei_Count <> (Nuclei_ObjectNumber IS NOT NULL)::INTEGER',
    ),
]

# Position checks. They do not stop the conversion, because a correct segmentation can break
# them in rare cases. The report gives their counts. On the test plate all counts were 0.
_BOX = 'Cells_AreaShape_BoundingBox{}_{}'
GEOMETRY = [
    (
        'nucleus centre outside the cell bounding box',
        ('Nuclei_Location_Center_X', 'Nuclei_Location_Center_Y') + tuple(_BOX.format(m, a) for m in ('Minimum', 'Maximum') for a in 'XY'),
        ' OR '.join(f'Nuclei_Location_Center_{a} {op} {_BOX.format(m, a)}' for a in 'XY' for op, m in (('<', 'Minimum'), ('>', 'Maximum'))),
    ),
    (
        'cytoplasm bounding box outside the cell bounding box',
        tuple(f'{o}_AreaShape_BoundingBox{m}_{a}' for o in ('Cells', 'Cytoplasm') for m in ('Minimum', 'Maximum') for a in 'XY'),
        ' OR '.join(
            f'Cytoplasm_AreaShape_BoundingBox{m}_{a} {op} {_BOX.format(m, a)}'
            for a in 'XY'
            for op, m in (('<', 'Minimum'), ('>', 'Maximum'))
        ),
    ),
]


def check_order(con, path, plates):
    """Prove that the rows of a Parquet file are in MERGE order: plate, then image, then cell.

    MERGE writes each plate table sorted by (Metadata_PlateImageNumber, Metadata_ObjectNumber),
    and stops if a key repeats or goes back. So the rows must strictly increase by
    (plate position, image, cell) in file order. This also proves that no cell occurs twice.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        The DuckDB connection.
    path : Path
        The Parquet file.
    plates : list of str
        The plate names in output order.

    Raises
    ------
    ValueError
        With the first row that breaks the order.
    """
    rank = '[' + ', '.join(sql_text(p) for p in plates) + ']'
    bad = con.execute(f"""
        WITH keyed AS (
            SELECT file_row_number AS r, list_position({rank}, Metadata_Plate) AS p,
                   Metadata_PlateImageNumber AS i, Metadata_ObjectNumber AS o
            FROM read_parquet({sql_text(str(path))}, file_row_number = true)
        ), paired AS (
            SELECT *, lag(p) OVER w AS lp, lag(i) OVER w AS li, lag(o) OVER w AS lo
            FROM keyed WINDOW w AS (ORDER BY r)
        )
        SELECT r, p, i, o, lp, li, lo FROM paired
        WHERE p IS NULL OR i IS NULL OR o IS NULL
           OR (lp IS NOT NULL AND NOT (p > lp OR (p = lp AND (i > li OR (i = li AND o > lo)))))
        ORDER BY r LIMIT 1
    """).fetchone()
    if bad:
        raise ValueError(
            f'{path.name}: row {bad[0]} (plate position, image, cell) = {bad[1:4]} does not come after the row before it, {bad[4:7]}'
        )


def check_content(con, path, plates, schema):
    """Prove that the Parquet rows hold the same values as the CSV rows, plate by plate.

    The check reads the CSV files a second time and compares, for each plate, the number of rows
    and the sum of a hash of every full row (all columns, nulls included). One changed value,
    or values moved to another row, changes the sum. Together with check_order, this shows that
    row n of the Parquet file is row n of the CSV.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        The DuckDB connection.
    path : Path
        The Parquet file.
    plates : list of tuple
        (plate name, CSV table, cells) of the plates in this file.
    schema : dict
        Column -> DuckDB type.

    Raises
    ------
    ValueError
        If a plate differs.
    """
    query = 'SELECT Metadata_Plate, count(*), sum(hash(t)) FROM {} t GROUP BY Metadata_Plate'
    expected = dict(
        (p, (n, h)) for p, n, h in con.execute(query.format(read_csv_sql([table for _, table, _ in plates], schema))).fetchall()
    )
    found = dict((p, (n, h)) for p, n, h in con.execute(query.format(f'read_parquet({sql_text(str(path))})')).fetchall())
    differ = sorted(p for p in expected.keys() | found.keys() if expected.get(p) != found.get(p))
    if differ:
        raise ValueError(f'{path.name}: row values differ from the CSV for plate(s) {differ}')


def check_cells(con, path, header):
    """Check that the parts of each row belong to one cell, and that each image has all its cells.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        The DuckDB connection.
    path : Path
        The Parquet file.
    header : list of str
        The columns.

    Returns
    -------
    dict
        Check -> rows that break it, for the IDENTITY and GEOMETRY checks whose columns exist,
        and 'images whose row count differs from Image_Count_Cells'.

    Raises
    ------
    ValueError
        If an IDENTITY check or the per-image count fails.
    """
    present = set(header)
    rules = [(name, condition) for name, needed, condition in IDENTITY + GEOMETRY if present.issuperset(needed)]
    source = f'read_parquet({sql_text(str(path))})'
    counts = {}
    if rules:
        select = ', '.join(f'count(*) FILTER (WHERE {condition})' for _, condition in rules)
        counts = dict(zip((name for name, _ in rules), con.execute(f'SELECT {select} FROM {source}').fetchone()))
    if 'Image_Count_Cells' in present:
        counts['images whose row count differs from Image_Count_Cells'] = con.execute(f"""
            SELECT count(*) FROM (
                SELECT any_value(Image_Count_Cells) AS expected, count(*) AS rows FROM {source}
                GROUP BY Metadata_Plate, Metadata_PlateImageNumber
            ) WHERE expected <> rows
        """).fetchone()[0]
    geometry = {name for name, *_ in GEOMETRY}
    failed = {name: n for name, n in counts.items() if n and name not in geometry}
    if failed:
        raise ValueError(f'{path.name}: rows that mix cells: {failed}')
    return counts


def check(con, path, plates, header, schema):
    """Check one Parquet file: columns, cells per plate, order, values, cell identity, and no NaN or inf.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        The DuckDB connection.
    path : Path
        The Parquet file.
    plates : list of tuple
        (plate name, CSV table, cells) of the plates in this file, in output order.
    header : list of str
        The CSV header.
    schema : dict
        Column -> DuckDB type.

    Returns
    -------
    nulls : dict
        The null count of each column, from the Parquet metadata.
    cells : dict
        The counts of ``check_cells()``.

    Raises
    ------
    ValueError
        On the first check that fails.
    """
    source = f'read_parquet({sql_text(str(path))})'
    columns = [row[0] for row in con.execute(f'DESCRIBE SELECT * FROM {source}').fetchall()]
    if columns != header:
        raise ValueError(f'{path.name}: the Parquet columns differ from the CSV header')
    expected = {plate: cells for plate, _, cells in plates}
    counts = dict(con.execute(f'SELECT Metadata_Plate, count(*) FROM {source} GROUP BY Metadata_Plate').fetchall())
    if counts != expected:
        raise ValueError(f'{path.name}: cells per plate {counts}, MERGE reports {expected}')
    check_order(con, path, [plate for plate, _, _ in plates])
    cells = check_cells(con, path, header)
    check_content(con, path, plates, schema)

    # The null tokens turned NaN and inf into nulls. A full scan proves that none is left.
    doubles = [name for name, dtype in schema.items() if dtype == 'DOUBLE']
    for start in range(0, len(doubles), 500):
        batch = doubles[start : start + 500]
        select = ', '.join(f'count(*) FILTER (WHERE isnan("{c}") OR isinf("{c}"))' for c in batch)
        bad = {c: n for c, n in zip(batch, con.execute(f'SELECT {select} FROM {source}').fetchone()) if n}
        if bad:
            raise ValueError(f'{path.name}: NaN or inf left in {len(bad)} columns, for example {list(bad.items())[:5]}')
    nulls = con.execute(f"""
        SELECT path_in_schema, sum(stats_null_count)::BIGINT FROM parquet_metadata({sql_text(str(path))})
        GROUP BY path_in_schema
    """).fetchall()
    return dict(nulls), cells


def main():
    """Parse the arguments, convert the plate tables, and write the reports. Exit with a message on an error."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('results', type=Path, help='the OUT folder of the plate-by-plate run')
    parser.add_argument(
        '--out',
        type=Path,
        help='output file (default: <results>/all_plates.parquet), or folder with --per-plate (default: <results>/parquet)',
    )
    parser.add_argument('--per-plate', action='store_true', help='write one Parquet file per plate into a folder')
    parser.add_argument('--threads', type=int, default=4, help='DuckDB threads (default: 4)')
    parser.add_argument('--memory', default='16GB', help='DuckDB memory limit; data above it spills to disk (default: 16GB)')
    args = parser.parse_args()
    out = args.out or args.results / ('parquet' if args.per_plate else 'all_plates.parquet')

    try:
        if out.exists():
            raise ValueError(f'{out} exists. Delete it or choose another --out.')
        tables = plate_tables(args.results)

        # All plates must share one header, so that the output is one table.
        header = read_header(tables[0][1])
        for plate, table, _ in tables[1:]:
            if read_header(table) != header:
                raise ValueError(f'{plate}: columns differ from {tables[0][0]}')
        schema = {name: column_type(name) for name in header}
        size = sum(table.stat().st_size for _, table, _ in tables)
        print(
            f'{len(tables)} plates, {sum(c for *_, c in tables):,} cells, {len(header)} columns, '
            f'{size / 2**30:.1f} GiB of CSV. The Parquet output needs about 60% of that space.'
        )

        # One target per output file: (final path, plates in it).
        if args.per_plate:
            out.mkdir(parents=True)
            targets = [(out / f'{plate}.parquet', [(plate, table, cells)]) for plate, table, cells in tables]
        else:
            targets = [(out, tables)]
        temp = out.parent / f'.duckdb-tmp-{out.name}'
        temp.mkdir(parents=True, exist_ok=True)
        report = {'sources': {plate: str(table) for plate, table, _ in tables}, 'files': {}}
        try:
            with duckdb.connect() as con:
                con.execute(f"SET memory_limit = '{args.memory}'")
                con.execute(f'SET threads = {args.threads}')
                con.execute(f'SET temp_directory = {sql_text(str(temp))}')
                for target, plates in targets:
                    partial = target.with_name(target.name + '.partial')
                    try:
                        print(f'Writing {target.name} from {len(plates)} plate(s)', flush=True)
                        convert(con, [table for _, table, _ in plates], partial, schema)
                        nulls, cell_checks = check(con, partial, plates, header, schema)
                        partial.rename(target)
                    except BaseException:
                        partial.unlink(missing_ok=True)
                        raise
                    stem = target.name.removesuffix('.parquet')
                    with (target.parent / f'{stem}.null_counts.csv').open('w', newline='') as stream:
                        writer = csv.writer(stream)
                        writer.writerow(['column', 'n_null'])
                        writer.writerows(sorted(nulls.items(), key=lambda item: -item[1]))
                    report['files'][str(target)] = {
                        'cells': {plate: cells for plate, _, cells in plates},
                        'columns': len(header),
                        'columns_with_nulls': sum(n > 0 for n in nulls.values()),
                        'bytes': target.stat().st_size,
                        'order_and_values_match_csv': True,
                        'rows_breaking_cell_checks': cell_checks,
                    }
                    print(f'  {target.name}: {target.stat().st_size / 2**30:.1f} GiB, checks passed', flush=True)
                    for name, n in cell_checks.items():
                        if n:
                            print(f'  Warning: {n:,} rows with {name}', flush=True)
        finally:
            shutil.rmtree(temp, ignore_errors=True)
    except (ValueError, OSError, duckdb.Error) as error:
        sys.exit(f'Conversion failed: {error}')

    report_path = out / 'report.json' if args.per_plate else out.with_name(f'{out.name.removesuffix(".parquet")}.report.json')
    report_path.write_text(json.dumps(report, indent=2))
    print(f'Wrote {out} and {report_path}')


if __name__ == '__main__':
    main()
