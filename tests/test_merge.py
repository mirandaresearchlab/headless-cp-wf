"""Unit tests for the per-cell merge and its Parquet output (bin/merge_features.py).

The tests build small fake batch folders in the same format as CellProfiler exports.
"""

import csv
import gzip
import io
import json
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


# The scripts in bin/ are not a package. Add the folder to the import path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import merge_features
from merge_features import check_parquet, merge_plate, to_parquet
from cp_inputs import write_csv


# Three image sets of one plate, and the object names that contract.json would give.
SITES = ["Site-1", "Site-2", "Site-3"]
PARTS = dict(cells="Cells", nuclei="Nuclei", cytoplasm="Cytoplasm")


def batch(root, name, sites, cells):
    """Write one fake batch folder, in the format that run_task.py leaves behind.

    Each cell has one cytoplasm and one nucleus. Object rows are written in reverse, and
    nuclei use other numbers than their cells. So the tests prove that the merge sorts the
    rows and joins the nuclei by Parent_Cells.

    Args:
        root: the folder to create the batch in.
        name: the batch name, e.g. "batch_0001".
        sites: the image sets of this batch.
        cells: the number of cells per image set, e.g. {"Site-1": 2}.

    Returns:
        The batch folder.
    """
    folder = root / name
    meta = lambda n, site: dict(  # noqa: E731
        ImageNumber=str(n),
        Metadata_Plate="P1",
        Metadata_Batch=name,
        Metadata_Acquisition=site,
        Metadata_Well="A01",
    )
    images, objects = [], {t: [] for t in PARTS.values()}

    # One Image row per image set, and Cells, Cytoplasm and Nuclei rows for each cell.
    for n, site in enumerate(sites, 1):
        count = cells[site]
        images.append(
            dict(
                meta(n, site),
                **{f"Count_{t}": f"{count}.0" for t in PARTS.values()},
                Intensity_MeanIntensity_DNA=f"{n}.5",
            )
        )
        for o in range(count, 0, -1):  # Reversed: the merge must sort.
            objects["Cells"].append(
                dict(
                    meta(n, site),
                    ObjectNumber=str(o),
                    Children_Nuclei_Count="1",
                    AreaShape_Area=f"{100 + o}",
                )
            )
            objects["Cytoplasm"].append(
                dict(
                    meta(n, site),
                    ObjectNumber=str(o),
                    Parent_Cells=str(o),
                    AreaShape_Area=f"{50 + o}",
                )
            )

            # Nuclei numbering differs from cell numbering. The join must use Parent_Cells.
            objects["Nuclei"].append(
                dict(
                    meta(n, site),
                    ObjectNumber=str(count + 1 - o),
                    Parent_Cells=str(o),
                    AreaShape_Area=f"{10 + o}",
                )
            )
    write_csv(folder / "features/Image.csv", images)

    # A table without rows still needs its header, as CellProfiler writes it.
    for table, rows in objects.items():
        header = sorted(meta(1, "")) + sorted(set(rows[0]) - set(meta(1, ""))) if rows else None
        header = header or sorted(meta(1, "")) + {"Cells": ["AreaShape_Area", "Children_Nuclei_Count", "ObjectNumber"]}.get(
            table, ["AreaShape_Area", "ObjectNumber", "Parent_Cells"]
        )
        with (folder / f"features/{table}.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=header)
            writer.writeheader()
            writer.writerows(rows)
    (folder / "features/Experiment.csv").write_text("Key,Value\nRun,1\n")

    # Compress the tables the same way run_task.py does after validation.
    for path in (folder / "features").glob("*.csv"):
        write_text(path.with_suffix(".csv.gz"), path.read_text())
        path.unlink()

    # validation.json marks a batch that passed its checks.
    (folder / "validation.json").write_text("{}")
    return folder


def read_text(path):
    """Read a gzip text file."""
    with gzip.open(path, "rt", newline="") as stream:
        return stream.read()


def write_text(path, text):
    """Write a gzip text file."""
    with gzip.open(path, "wt", newline="") as stream:
        stream.write(text)


def plate(tmp_path, cells=None):
    """Make plate P1 with three image sets in two batches.

    Args:
        tmp_path: the pytest temporary folder.
        cells: the number of cells per image set. Site-2 has no cells by default.

    Returns:
        (manifest, batch folders). The batches are listed out of order on purpose.
    """
    cells = cells or {"Site-1": 2, "Site-2": 0, "Site-3": 1}
    manifest = tmp_path / "plate.csv"
    write_csv(manifest, [dict(Metadata_Acquisition=s) for s in SITES])
    batches = [
        batch(tmp_path, "batch_0002", SITES[2:], cells),
        batch(tmp_path, "batch_0001", SITES[:2], cells),
    ]
    return manifest, batches


def read(path):
    """Read a gzip CSV file as a list of row dicts."""
    return list(csv.DictReader(io.StringIO(read_text(path))))


def test_one_row_per_cell_in_single_batch_order(tmp_path):
    """One row per cell, in plate order. Each row joins the correct cytoplasm, nucleus and image values."""
    manifest, batches = plate(tmp_path)
    report = merge_plate("P1", manifest, batches, PARTS, tmp_path / "P1.csv.gz")
    rows = read(tmp_path / "P1.csv.gz")

    # Rows in plate order. Site-2 has no cells, so plate image 2 has no rows.
    assert [
        (
            r["Metadata_PlateImageNumber"],
            r["Metadata_ImageNumber"],
            r["Metadata_ObjectNumber"],
        )
        for r in rows
    ] == [("1", "1", "1"), ("1", "1", "2"), ("3", "1", "1")]

    # Each row holds the values of its own cell, cytoplasm, nucleus and image.
    assert [
        (
            r["Cells_AreaShape_Area"],
            r["Cytoplasm_AreaShape_Area"],
            r["Nuclei_AreaShape_Area"],
        )
        for r in rows
    ] == [("101", "51", "11"), ("102", "52", "12"), ("101", "51", "11")]
    assert [r["Image_Intensity_MeanIntensity_DNA"] for r in rows] == [
        "1.5",
        "1.5",
        "1.5",
    ]
    assert [r["Nuclei_ObjectNumber"] for r in rows] == ["2", "1", "1"]

    # Metadata comes first, and only once.
    header = list(rows[0])
    assert header[:5] == [
        "Metadata_Acquisition",
        "Metadata_Batch",
        "Metadata_Plate",
        "Metadata_Well",
        "Metadata_PlateImageNumber",
    ]
    assert not any(c.endswith("_ImageNumber") and c != "Metadata_ImageNumber" for c in header)
    assert sum(c.startswith("Metadata_Plate") for c in header) == 2
    assert report["cells"] == 3 and report["cells_without_nucleus"] == 0


def test_missing_batch_fails(tmp_path):
    """If a batch is missing, the merge stops. It does not write a partial plate."""
    manifest, batches = plate(tmp_path)

    # Give only the second batch.
    with pytest.raises(ValueError, match="every plate image set"):
        merge_plate("P1", manifest, batches[1:], PARTS, tmp_path / "P1.csv.gz")


def test_column_mismatch_between_batches_fails(tmp_path):
    """Batches with different columns stop the merge."""
    manifest, batches = plate(tmp_path)
    path = batches[0] / "features/Cells.csv.gz"

    # Rename one column in one batch only.
    write_text(path, read_text(path).replace("AreaShape_Area", "AreaShape_Perimeter", 1))
    with pytest.raises(ValueError, match="columns differ"):
        merge_plate("P1", manifest, batches, PARTS, tmp_path / "P1.csv.gz")


def test_unvalidated_batch_fails(tmp_path):
    """A batch without validation.json stops the merge."""
    manifest, batches = plate(tmp_path)
    (batches[0] / "validation.json").unlink()
    with pytest.raises(ValueError, match="did not pass validation"):
        merge_plate("P1", manifest, batches, PARTS, tmp_path / "P1.csv.gz")


def test_object_rows_must_match_counts(tmp_path):
    """Object rows must agree with Count_<Object> in Image.csv."""
    manifest, batches = plate(tmp_path)
    path = batches[1] / "features/Image.csv.gz"

    # Say there are 3 cells where the table has 2.
    write_text(path, read_text(path).replace("2.0", "3.0"))
    with pytest.raises(ValueError, match="Count_"):
        merge_plate("P1", manifest, batches, PARTS, tmp_path / "P1.csv.gz")


def test_cell_with_two_nuclei_fails(tmp_path):
    """A cell with two nuclei stops the merge. The merge does not pick one."""
    manifest, batches = plate(tmp_path)
    path = batches[1] / "features/Nuclei.csv.gz"
    rows = read(path)

    # Give the second nucleus the same parent cell as the first.
    rows[1]["Parent_Cells"] = rows[0]["Parent_Cells"]
    text = io.StringIO()
    writer = csv.DictWriter(text, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    write_text(path, text.getvalue())
    with pytest.raises(ValueError, match="several nuclei"):
        merge_plate("P1", manifest, batches, PARTS, tmp_path / "P1.csv.gz")


def rewrite(path, change):
    """Change the rows of one gzip table in place.

    Args:
        path: the .csv.gz table.
        change: a function that gets the list of row dicts and changes it in place.
    """
    rows = read(path)
    change(rows)
    text = io.StringIO()
    writer = csv.DictWriter(text, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    write_text(path, text.getvalue())


@pytest.mark.parametrize("table, column", [("Nuclei", "Parent_Cells"), ("Cytoplasm", "ObjectNumber")])
def test_object_of_a_missing_cell_fails(tmp_path, table, column):
    """A nucleus or cytoplasm that names a cell number with no cell row stops the merge.

    Without this check the merge would leave the object out of the table, and the number of
    objects in the table would be smaller than Count_<Object> in Image.csv.
    """
    manifest, batches = plate(tmp_path)

    # Site-1 has cells 1 and 2. Point the first object to cell 3, which does not exist.
    def to_cell_three(rows):
        rows[0][column] = "3"
        if table == "Cytoplasm":
            rows[0]["Parent_Cells"] = "3"

    rewrite(batches[1] / f"features/{table}.csv.gz", to_cell_three)
    with pytest.raises(ValueError, match="no cell"):
        merge_plate("P1", manifest, batches, PARTS, tmp_path / "P1.csv.gz")


def test_report_accounts_for_every_object(tmp_path):
    """The report gives the objects of each table, and each one is either joined or counted as unjoined."""
    manifest, batches = plate(tmp_path)

    # Site-1: the first nucleus has no cell (Parent_Cells 0), so cell 2 has no nucleus.
    rewrite(batches[1] / "features/Nuclei.csv.gz", lambda rows: rows[0].update(Parent_Cells="0"))
    rewrite(batches[1] / "features/Cells.csv.gz", lambda rows: rows[0].update(Children_Nuclei_Count="0"))
    report = merge_plate("P1", manifest, batches, PARTS, tmp_path / "P1.csv.gz")

    # Count_<Object> of the three images: 2 + 0 + 1 for every table.
    assert report["objects"] == {"Cells": 3, "Cytoplasm": 3, "Nuclei": 3}
    assert report["cells"] == 3 == len(read(tmp_path / "P1.csv.gz"))
    assert report["nuclei_without_cell"] == 1 and report["cells_without_nucleus"] == 1
    assert report["cells"] - report["cells_without_nucleus"] + report["nuclei_without_cell"] == report["objects"]["Nuclei"]


def test_interleaved_batches_fail(tmp_path):
    """Batches that are not consecutive slices of the plate stop the merge."""
    manifest = tmp_path / "plate.csv"
    write_csv(manifest, [dict(Metadata_Acquisition=s) for s in SITES])
    cells = {s: 1 for s in SITES}

    # Batch 1 holds image sets 1 and 3, batch 2 holds image set 2. PREPARE never makes such batches.
    batches = [
        batch(tmp_path, "batch_0001", [SITES[0], SITES[2]], cells),
        batch(tmp_path, "batch_0002", SITES[1:2], cells),
    ]
    with pytest.raises(ValueError, match="out-of-order"):
        merge_plate("P1", manifest, batches, PARTS, tmp_path / "P1.csv.gz")


def parquet_plate(tmp_path):
    """Merge plate P1 and convert it to Parquet.

    Site-1 has a cell without a nucleus (blank Nuclei columns), and one Image value is nan.

    Returns:
        (merged CSV, Parquet file, MERGE report).
    """
    # Make a plate with one cell that has no nucleus, and one image with a nan value.
    manifest, batches = plate(tmp_path)

    # rewrite the first nucleus to have no parent cell, and the first cell to have no children nuclei.
    rewrite(batches[1] / "features/Nuclei.csv.gz", lambda rows: rows[0].update(Parent_Cells="0"))
    rewrite(batches[1] / "features/Cells.csv.gz", lambda rows: rows[0].update(Children_Nuclei_Count="0"))
    rewrite(batches[0] / "features/Image.csv.gz", lambda rows: rows[0].update(Intensity_MeanIntensity_DNA="nan"))
    
    # Merge the plate and convert it to Parquet. The Parquet file has one row per cell, with every value parsed by the fixed type rule.
    report = merge_plate("P1", manifest, batches, PARTS, tmp_path / "P1.csv.gz")
    header = to_parquet(tmp_path / "P1.csv.gz", tmp_path / "P1.parquet")
    
    # checks that the Parquet file has the same number of rows as the CSV, and that every value is parsed correctly.
    check_parquet(tmp_path / "P1.parquet", header, "P1", report["cells"], PARTS)

    return tmp_path / "P1.csv.gz", tmp_path / "P1.parquet", report


@pytest.mark.parametrize("row_group", [1, 10_000])
def test_parquet_matches_csv_value_by_value(tmp_path, monkeypatch, row_group):
    """Row n of the Parquet file is row n of the merged CSV, with every value parsed by the fixed type rule."""

    # set the row group size to a small number to test that the Parquet file is written in multiple row groups.
    monkeypatch.setattr(merge_features, "ROW_GROUP_SIZE", row_group)
    table, parquet, report = parquet_plate(tmp_path)

    # set expected table and found table to the CSV and Parquet files, respectively. 
    # Check that they have the same number of rows, and that every value matches the expected type and value.
    expected = read(table)
    found = pq.read_table(parquet).to_pylist()

    # check that the number of rows in the CSV, Parquet, and report are all equal to 3.
    assert len(found) == len(expected) == report["cells"] == 3

    # iterate over the expected and found rows, checking that each value matches the expected type and value.
    for want, got in zip(expected, found):
        assert list(got) == list(want)
        for column, text in want.items():
            kind = merge_features.column_type(column)
            value = (
                None
                if text in merge_features.NULL_TOKENS
                else (str(text) if kind == pa.string() else int(text) if kind == pa.int64() else float(text))
            )
            assert got[column] == value, column

    # if the row group size is 1, check that the Parquet file has 3 row groups.
    if row_group == 1:
        assert pq.ParquetFile(parquet).metadata.num_row_groups == 3


def test_parquet_types_do_not_depend_on_values(tmp_path):
    """Metadata is text, image and object numbers are integers, measurements are doubles, even in an all-empty column."""
    # set up a plate with one cell that has no nucleus, and one image with a nan value. Merge the plate and convert it to Parquet.
    _, parquet, _ = parquet_plate(tmp_path)

    # set schema to the Parquet schema, and check that the types of the columns are as expected.
    schema = pq.read_schema(parquet)

    # check for the expected types of the columns in the Parquet schema. 
    # Metadata columns should be strings, image and object numbers should be integers, 
    # and measurements should be doubles.
    assert schema.field("Metadata_Plate").type == pa.string()
    assert schema.field("Metadata_PlateImageNumber").type == pa.int64()
    assert schema.field("Metadata_ObjectNumber").type == pa.int64()
    assert schema.field("Cells_AreaShape_Area").type == pa.float64()

    # Image_Intensity_MeanIntensity_DNA is nan in one image: it is a null, not a text column.
    assert schema.field("Image_Intensity_MeanIntensity_DNA").type == pa.float64()
    assert pq.read_table(parquet, columns=["Image_Intensity_MeanIntensity_DNA"]).column(0).null_count == 1


def test_value_that_is_not_a_number_fails(tmp_path):
    """A measurement that is not a number or a missing-value token stops the conversion."""
    manifest, batches = plate(tmp_path)
    rewrite(batches[1] / "features/Cells.csv.gz", lambda rows: rows[0].update(AreaShape_Area="12,5"))
    merge_plate("P1", manifest, batches, PARTS, tmp_path / "P1.csv.gz")
    with pytest.raises(ValueError):
        to_parquet(tmp_path / "P1.csv.gz", tmp_path / "P1.parquet")


def tampered(parquet, out, change):
    """Write a copy of a Parquet file after a change to its rows (a function of the list of row dicts)."""
    table = pq.read_table(parquet)
    rows = table.to_pylist()
    change(rows)
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), out)
    return table.schema.names


def test_check_finds_two_swapped_cells(tmp_path):
    """Two cells change places: the order check fails."""
    _, parquet, report = parquet_plate(tmp_path)
    header = tampered(parquet, tmp_path / "bad.parquet", lambda rows: rows.insert(0, rows.pop(1)))
    with pytest.raises(ValueError, match="order"):
        check_parquet(tmp_path / "bad.parquet", header, "P1", report["cells"], PARTS)


def test_check_finds_nucleus_of_another_cell(tmp_path):
    """The Nuclei columns move down one row, so a row holds the nucleus of another cell: the identity check fails."""
    # read the Parquet file and the report from merging the plate, and tamper with the rows by shifting the Nuclei
    #  columns down one row. Then check that the Parquet file fails the identity check.
    _, parquet, report = parquet_plate(tmp_path)

    # setting internal function for shifting the Nuclei columns down one row, so that each row holds the nucleus of another cell.
    def shift(rows):
        nuclei = [{c: v for c, v in r.items() if c.startswith("Nuclei_")} for r in rows]
        for row, nucleus in zip(rows, [dict.fromkeys(nuclei[0])] + nuclei[:-1]):
            row.update(nucleus)

    # setting header to the schema 
    header = tampered(parquet, tmp_path / "bad.parquet", shift)
    with pytest.raises(ValueError, match="Nuclei_Parent_Cells"):
        check_parquet(tmp_path / "bad.parquet", header, "P1", report["cells"], PARTS)


def test_check_finds_a_lost_cell(tmp_path):
    """The Parquet file has fewer rows than MERGE counted: the row count check fails."""
    _, parquet, report = parquet_plate(tmp_path)
    header = tampered(parquet, tmp_path / "bad.parquet", lambda rows: rows.pop())
    with pytest.raises(ValueError, match="rows"):
        check_parquet(tmp_path / "bad.parquet", header, "P1", report["cells"], PARTS)


def test_command_writes_only_the_parquet_table(tmp_path):
    """The plate command, as MERGE runs it, publishes <plate>.parquet and deletes its temporary CSV."""
    manifest, batches = plate(tmp_path)
    folder = tmp_path / "batches"
    folder.mkdir()
    for b in batches:
        b.rename(folder / b.name)
    contract = tmp_path / "contract.json"
    contract.write_text(json.dumps({"compartments": PARTS}))
    script = Path(merge_features.__file__)
    args = ["plate", "--plate", "P1", "--manifest", manifest, "--batches", folder, "--contract", contract]
    run = subprocess.run(
        [sys.executable, script, *args, "--out", tmp_path / "out/P1.parquet", "--report", tmp_path / "merge.json"],
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["P1.parquet"]
    assert pq.read_metadata(tmp_path / "out/P1.parquet").num_rows == json.loads((tmp_path / "merge.json").read_text())["cells"] == 3
