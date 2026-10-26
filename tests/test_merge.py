"""Unit tests for the per-cell merge and the plate concatenation (bin/merge_features.py).

The tests build small fake batch folders in the same format as CellProfiler exports.
"""

import csv
import gzip
import io
import sys
from pathlib import Path

import pytest


# The scripts in bin/ are not a package. Add the folder to the import path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from merge_features import concatenate, header_member, merge_plate
from prepare import write_csv


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
    meta = lambda n, site: dict(
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
        header = (
            sorted(meta(1, "")) + sorted(set(rows[0]) - set(meta(1, "")))
            if rows
            else None
        )
        header = header or sorted(meta(1, "")) + {
            "Cells": ["AreaShape_Area", "Children_Nuclei_Count", "ObjectNumber"]
        }.get(table, ["AreaShape_Area", "ObjectNumber", "Parent_Cells"])
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
    assert not any(
        c.endswith("_ImageNumber") and c != "Metadata_ImageNumber" for c in header
    )
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
    write_text(
        path, read_text(path).replace("AreaShape_Area", "AreaShape_Perimeter", 1)
    )
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


def plate_table(path, header, rows):
    """Write a plate table the way MERGE does: a gzip part with the header, then one with the rows.

    Args:
        path: the .csv.gz file to write.
        header: the column names.
        rows: the rows, as lists of values.
    """
    text = io.StringIO()
    csv.writer(text).writerows(rows)
    path.write_bytes(header_member(header) + gzip.compress(text.getvalue().encode()))


def test_merge_writes_header_as_separate_member(tmp_path):
    """MERGE output starts with the header member, so CONCAT can join plates without decompressing."""
    manifest, batches = plate(tmp_path)
    merge_plate("P1", manifest, batches, PARTS, tmp_path / "P1.csv.gz")
    header = read_text(tmp_path / "P1.csv.gz").splitlines()[0].split(",")

    # The file must start with exactly the bytes that CONCAT expects to skip.
    assert (tmp_path / "P1.csv.gz").read_bytes().startswith(header_member(header))


def test_concatenate_joins_plates_in_name_order(tmp_path):
    """Plates are joined in name order with one header. The rows are unchanged."""
    plate_table(tmp_path / "B.csv.gz", ["Metadata_Plate", "X"], [["B", "2"]])
    plate_table(
        tmp_path / "A.csv.gz", ["Metadata_Plate", "X"], [["A", "1"], ["A", "3"]]
    )
    report = concatenate(
        [tmp_path / "B.csv.gz", tmp_path / "A.csv.gz"], tmp_path / "all.csv.gz"
    )

    # Plate A comes first even though it was given second. One header, all rows.
    assert (
        read_text(tmp_path / "all.csv.gz")
        == "Metadata_Plate,X\r\nA,1\r\nA,3\r\nB,2\r\n"
    )
    assert report["plates"] == ["A", "B"] and report["columns"] == 2


def test_concatenate_requires_identical_columns(tmp_path):
    """Different column sets or orders stop the concatenation."""
    plate_table(tmp_path / "A.csv.gz", ["Metadata_Plate", "X"], [["A", "1"]])

    # Same columns in another order.
    plate_table(tmp_path / "B.csv.gz", ["X", "Metadata_Plate"], [["2", "B"]])
    with pytest.raises(ValueError, match="different order: True"):
        concatenate(
            [tmp_path / "A.csv.gz", tmp_path / "B.csv.gz"], tmp_path / "all.csv.gz"
        )

    # A different column.
    plate_table(tmp_path / "B.csv.gz", ["Metadata_Plate", "Y"], [["B", "2"]])
    with pytest.raises(ValueError, match=r"missing \['X'\], extra \['Y'\]"):
        concatenate(
            [tmp_path / "A.csv.gz", tmp_path / "B.csv.gz"], tmp_path / "all.csv.gz"
        )


def test_concatenate_rejects_tables_not_written_by_merge(tmp_path):
    """A plain one-member gzip CSV is refused, because its rows cannot be copied without the header."""
    plate_table(tmp_path / "A.csv.gz", ["Metadata_Plate", "X"], [["A", "1"]])

    # A normal gzip CSV: header and rows in one part.
    write_text(tmp_path / "B.csv.gz", "Metadata_Plate,X\r\nB,2\r\n")
    with pytest.raises(ValueError, match="not written by MERGE"):
        concatenate(
            [tmp_path / "A.csv.gz", tmp_path / "B.csv.gz"], tmp_path / "all.csv.gz"
        )
