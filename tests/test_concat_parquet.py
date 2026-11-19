"""Tests for the Parquet join of plate tables (scripts/concat_plate_tables.py).

The question: after the join, is row n of the Parquet file still row n of the CSV, and do the
Cells, Cytoplasm and Nuclei values of one row still belong to one cell?

The tests need DuckDB, which the CellProfiler environment does not have. Run them with:
    uv run --python 3.12 --with duckdb==1.4.1 --with pytest pytest -q tests/test_concat_parquet.py
"""

import csv
import gzip
import json
import random
import subprocess
import sys
from pathlib import Path

import pytest

duckdb = pytest.importorskip('duckdb')

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'concat_plate_tables.py'
sys.path.insert(0, str(SCRIPT.parent))
import concat_plate_tables as concat  # noqa: E402

HEADER = [
    'Metadata_Plate',
    'Metadata_Well',
    'Metadata_PlateImageNumber',
    'Metadata_ImageNumber',
    'Metadata_ObjectNumber',
    'Image_Count_Cells',
    'Image_Intensity_MeanIntensity_DNA',
    'Cells_ObjectNumber',
    'Cells_Number_Object_Number',
    'Cells_Children_Nuclei_Count',
    'Cells_AreaShape_Area',
    'Cells_AreaShape_BoundingBoxMinimum_X',
    'Cells_AreaShape_BoundingBoxMaximum_X',
    'Cells_AreaShape_BoundingBoxMinimum_Y',
    'Cells_AreaShape_BoundingBoxMaximum_Y',
    'Cytoplasm_ObjectNumber',
    'Cytoplasm_Parent_Cells',
    'Cytoplasm_AreaShape_Area',
    'Cytoplasm_AreaShape_BoundingBoxMinimum_X',
    'Cytoplasm_AreaShape_BoundingBoxMaximum_X',
    'Cytoplasm_AreaShape_BoundingBoxMinimum_Y',
    'Cytoplasm_AreaShape_BoundingBoxMaximum_Y',
    'Nuclei_ObjectNumber',
    'Nuclei_Parent_Cells',
    'Nuclei_AreaShape_Area',
    'Nuclei_Location_Center_X',
    'Nuclei_Location_Center_Y',
]


def plate_rows(plate, images, seed):
    """Rows of one plate table in MERGE order, with a random number of cells per image.

    Every measurement is a different random number, so a value that moves to another row is
    visible. Some cells have no nucleus (blank Nuclei columns), and some values are nan.
    """
    rng = random.Random(seed)
    rows = []
    for image in range(1, images + 1):
        count = rng.choice([0, 1, 5, 40, 120])
        for cell in range(1, count + 1):
            x, y = rng.uniform(0, 1000), rng.uniform(0, 1000)
            has_nucleus = rng.random() > 0.05
            nucleus = (
                [str(count + 1 - cell), str(cell), f'{rng.uniform(50, 500):.6f}', f'{x + 1:.4f}', f'{y + 1:.4f}']
                if has_nucleus
                else [''] * 5
            )
            rows.append(
                [
                    plate,
                    f'A{image % 24:02d}',
                    str(image),
                    str(image % 7 + 1),
                    str(cell),
                    f'{count}.0',
                    'nan' if image % 11 == 0 else f'{rng.random():.12g}',
                    str(cell),
                    str(cell),
                    str(int(has_nucleus)),
                    f'{rng.uniform(500, 5000):.6f}',
                    f'{x - 10:.1f}',
                    f'{x + 10:.1f}',
                    f'{y - 10:.1f}',
                    f'{y + 10:.1f}',
                    str(cell),
                    str(cell),
                    f'{rng.uniform(100, 4000):.6f}',
                    f'{x - 9:.1f}',
                    f'{x + 9:.1f}',
                    f'{y - 9:.1f}',
                    f'{y + 9:.1f}',
                    *nucleus,
                ]
            )
    return rows


def results_folder(root, plates):
    """Make the OUT folder of a plate-by-plate run: DONE, MERGE report and table for each plate.

    Args:
        root: the folder to write into.
        plates: {plate name: rows}.

    Returns:
        The results folder.
    """
    results = root / 'results'
    for plate, rows in plates.items():
        run = root / 'runs' / plate
        (run / 'cp_features').mkdir(parents=True)
        (run / 'logs' / plate).mkdir(parents=True)
        with gzip.open(run / concat.TABLE, 'wt', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(HEADER)
            writer.writerows(rows)
        (run / 'logs' / plate / 'merge.json').write_text(json.dumps({'cells': len(rows)}))
        (results / plate).mkdir(parents=True)
        (results / plate / 'DONE').write_text(f'{run}\n')
    return results


@pytest.fixture
def three_plates(tmp_path):
    """Three plates, about 6,000 cells each, with plate names out of order on disk."""
    plates = {name: plate_rows(name, 150, seed) for seed, name in enumerate(['PB3_24h', 'PB1_1h', 'PB2_4h'])}
    return results_folder(tmp_path, plates), plates


def parquet_rows(path):
    """All rows of a Parquet file in file order, as text, the way they appear in the CSV."""
    with duckdb.connect() as con:
        rows = con.execute(
            f"SELECT * EXCLUDE (file_row_number) FROM read_parquet('{path}', file_row_number = true) ORDER BY file_row_number"
        ).fetchall()
    return rows


def as_csv_value(value, dtype):
    """Parse a CSV text value the way the conversion types it, for comparison."""
    if value in concat.NULL_TOKENS:
        return None
    return {'BIGINT': int, 'DOUBLE': float, 'VARCHAR': str}[dtype](value)


def converted(results, tmp_path, threads=4, row_group=97, per_plate=False):
    """Run convert and check, as main does, with small row groups so the file has many of them."""
    tables = concat.plate_tables(results)
    schema = {name: concat.column_type(name) for name in HEADER}
    targets = [(tmp_path / f'{p}.parquet', [(p, t, c)]) for p, t, c in tables] if per_plate else [(tmp_path / 'all.parquet', tables)]
    old, concat.ROW_GROUP_SIZE = concat.ROW_GROUP_SIZE, row_group
    try:
        with duckdb.connect() as con:
            con.execute(f'SET threads = {threads}')
            for target, plates in targets:
                concat.convert(con, [t for _, t, _ in plates], target, schema)
                concat.check(con, target, plates, HEADER, schema)
    finally:
        concat.ROW_GROUP_SIZE = old
    return targets, schema


@pytest.mark.parametrize('threads', [1, 8])
def test_every_row_is_the_same_cell_in_the_same_place(three_plates, tmp_path, threads):
    """Row n of the Parquet file equals row n of the CSV files, joined in plate name order.

    This compares every value of every row in Python, apart from the checks in the script.
    """
    results, plates = three_plates
    [(target, _)], schema = converted(results, tmp_path, threads=threads)
    expected = [tuple(as_csv_value(v, schema[c]) for v, c in zip(row, HEADER)) for name in sorted(plates) for row in plates[name]]
    found = parquet_rows(target)
    assert len(found) == len(expected) > 10_000
    for n, (want, got) in enumerate(zip(expected, found)):
        assert got == want, f'row {n} differs'


def test_per_plate_files_keep_order(three_plates, tmp_path):
    """With --per-plate, each file holds its own plate only, in the CSV order."""
    results, plates = three_plates
    targets, schema = converted(results, tmp_path, per_plate=True)
    for target, [(name, _, _)] in targets:
        keys = [(r[0], r[2], r[4]) for r in parquet_rows(target)]
        assert keys == [(name, int(r[2]), int(r[4])) for r in plates[name]]


def tampered(con, good, bad, select):
    """Write a copy of a good Parquet file with one change, given as a SELECT list."""
    con.execute(
        f"COPY (SELECT {select} FROM read_parquet('{good}', file_row_number = true) ORDER BY file_row_number) TO '{bad}' (FORMAT parquet)"
    )


@pytest.fixture
def good(three_plates, tmp_path):
    """A Parquet file that passed every check, with what is needed to check a changed copy."""
    results, _ = three_plates
    [(target, plates)], schema = converted(results, tmp_path)
    return target, plates, schema


def test_check_finds_two_swapped_rows(good, tmp_path):
    """Two neighbouring cells change places: the order check fails."""
    target, plates, schema = good
    bad = tmp_path / 'swapped.parquet'
    with duckdb.connect() as con:
        con.execute(f"""COPY (SELECT * EXCLUDE (file_row_number) FROM read_parquet('{target}', file_row_number = true)
                        ORDER BY CASE file_row_number WHEN 500 THEN 501 WHEN 501 THEN 500 ELSE file_row_number END)
                        TO '{bad}' (FORMAT parquet)""")
        with pytest.raises(ValueError, match='does not come after'):
            concat.check(con, bad, plates, HEADER, schema)


def test_check_finds_plates_in_wrong_order(good, tmp_path):
    """The plates are joined in another order: the order check fails."""
    target, plates, schema = good
    bad = tmp_path / 'plates.parquet'
    with duckdb.connect() as con:
        con.execute(f"""COPY (SELECT * EXCLUDE (file_row_number) FROM read_parquet('{target}', file_row_number = true)
                        ORDER BY Metadata_Plate DESC, file_row_number) TO '{bad}' (FORMAT parquet)""")
        with pytest.raises(ValueError, match='does not come after'):
            concat.check(con, bad, plates, HEADER, schema)


def test_check_finds_one_changed_value(good, tmp_path):
    """One measurement of one cell changes: the value check fails, even though order and IDs are right."""
    target, plates, schema = good
    bad = tmp_path / 'changed.parquet'
    with duckdb.connect() as con:
        tampered(
            con,
            target,
            bad,
            """* EXCLUDE (file_row_number) REPLACE (
            CASE WHEN file_row_number = 1234 THEN Cytoplasm_AreaShape_Area + 1e-9 ELSE Cytoplasm_AreaShape_Area END
            AS Cytoplasm_AreaShape_Area)""",
        )
        with pytest.raises(ValueError, match='row values differ'):
            concat.check(con, bad, plates, HEADER, schema)


def test_check_finds_nucleus_values_of_another_cell(good, tmp_path):
    """The nucleus columns of a row are shifted down by one row: the cell identity check fails."""
    target, plates, schema = good
    bad = tmp_path / 'shifted.parquet'
    nuclei = [c for c in HEADER if c.startswith('Nuclei_')]
    shifted = ', '.join(f'lag({c}) OVER (ORDER BY file_row_number) AS {c}' for c in nuclei)
    with duckdb.connect() as con:
        tampered(con, target, bad, f'* EXCLUDE (file_row_number) REPLACE ({shifted})')
        with pytest.raises(ValueError, match='rows that mix cells'):
            concat.check(con, bad, plates, HEADER, schema)


def test_check_finds_an_image_with_a_missing_cell(three_plates, tmp_path):
    """A plate table lost one cell, and its MERGE report agrees: the per-image count check fails."""
    results, plates = three_plates
    name = sorted(plates)[0]
    rows = plates[name]
    victim = next(n for n, r in enumerate(rows) if r[5] == '40.0')
    damaged = rows[:victim] + rows[victim + 1 :]
    root = tmp_path / 'damaged'
    root.mkdir()
    results = results_folder(root, {**plates, name: damaged})
    with pytest.raises(ValueError, match='Image_Count_Cells'):
        converted(results, root)


def test_command_line_writes_report(three_plates):
    """The script as the Slurm job runs it: the output exists and the report lists the checks."""
    results, plates = three_plates
    run = subprocess.run([sys.executable, str(SCRIPT), str(results), '--threads', '4', '--memory', '2GB'], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    report = json.loads((results / 'all_plates.report.json').read_text())
    [entry] = report['files'].values()
    assert entry['order_and_values_match_csv'] is True
    assert entry['cells'] == {name: len(rows) for name, rows in plates.items()}
    assert set(entry['rows_breaking_cell_checks'].values()) == {0}
    assert len(entry['rows_breaking_cell_checks']) == len(concat.IDENTITY) + len(concat.GEOMETRY) + 1
