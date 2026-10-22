#!/usr/bin/env python3
"""Merge the tables of all chunks (of one plate or of all plates) into one table per name.

CellProfiler starts ImageNumber at 1 in each chunk. If you only put the tables one after the other,
objects of different images get the same ImageNumber, and a join on ImageNumber would join cells to the wrong
images. Thus the merge makes ImageNumber unique in the merged tables, with the same value in the per-image and
the per-object tables. Two columns in front keep the original values:
  CPNF_Chunk            - the chunk of the row, for example PANC1_P01_chunk_0003.
  CPNF_ChunkImageNumber - the ImageNumber that CellProfiler wrote in that chunk.

The merged table has all columns of all chunks. A value that a chunk does not have stays empty. The
script reads and writes one row at a time, with only the Python standard library. Thus it works on large
object tables and with any python3.

The merge stops the run in these cases:
  * two chunks wrote the same mask file;
  * (--unique-metadata) the same plate, well and site occur twice in the image tables;
  * (--require-plate) a row of an image or object table has no Metadata_Plate;
  * (--check-compartments) the Image, Cells, Nuclei or Cytoplasm table, or a column that joins them, is
    missing.

Examples
--------
P1_chunk_0001 has image sets 1-50, and P1_chunk_0002 has image sets 1-50. In the merged tables,
image set 1 of P1_chunk_0002 gets ImageNumber 51 and CPNF_ChunkImageNumber 1.
"""

import argparse
import contextlib
import csv
import gzip
import json
import os
import sys
from collections import defaultdict

# Read and write all CSV files in the same way. "surrogateescape" keeps odd bytes as they are.
ENC = dict(encoding="utf-8", errors="surrogateescape")

# The table that connects masks to image sets (check_chunk.py). It has one row per mask, not per image set.
MANIFEST = "mask_manifest.csv"

# The tables of the compartments of a cell, and the columns that join them: each cytoplasm object to its cell
# (Parent_Cells) and its nucleus (Parent_Nuclei), and each object to its image (ImageNumber) and site.
# Upper and lower case of the table names are the same.
SITE_COLUMNS = ["Metadata_Plate", "Metadata_Well", "Metadata_Site"]
OBJECT_COLUMNS = ["ImageNumber", "ObjectNumber", *SITE_COLUMNS, "Number_Object_Number"]
COMPARTMENT_COLUMNS = {
    "Image.csv": ["ImageNumber", *SITE_COLUMNS],
    "Cells.csv": OBJECT_COLUMNS,
    "Nuclei.csv": OBJECT_COLUMNS,
    "Cytoplasm.csv": [*OBJECT_COLUMNS, "Parent_Cells", "Parent_Nuclei"],
}


def set_field_limit():
    """Allow very long CSV fields.

    CellProfiler can write long values, but the default limit of the csv module is small.
    """

    # Try the largest limit first. Some systems refuse it, so make it 10 times smaller until it works.
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def chunk_name(path):
    """Get the chunk name from the folder of its tables.

    Parameters
    ----------
    path : str
        A folder such as ".../features_chunk_0003".

    Returns
    -------
    str
        The chunk name, for example "chunk_0003".
    """
    base = os.path.basename(os.path.normpath(path))
    return base[len("features_") :] if base.startswith("features_") else base


def as_int(value):
    """Read an integer that CellProfiler sometimes writes as '3.0'.

    Parameters
    ----------
    value : str or int or float
        The value, for example "3.0".

    Returns
    -------
    int
        The integer, for example 3.

    Raises
    ------
    ValueError
        If the value is not a number.
    """
    return int(float(value))


def header_of(path):
    """Read the column names of a CSV file.

    Parameters
    ----------
    path : str
        Path of the CSV file.

    Returns
    -------
    list of str
        The column names (empty for an empty file).
    """
    with open(path, newline="", **ENC) as fh:
        return next(csv.reader(fh), [])


def max_image_number(path):
    """Find the highest ImageNumber in a table.

    Parameters
    ----------
    path : str
        Path of the CSV file.

    Returns
    -------
    int
        The highest ImageNumber, or 0 if the table has none. The function skips rows with bad values.
    """
    best = 0
    with open(path, newline="", **ENC) as fh:
        for row in csv.DictReader(fh):
            with contextlib.suppress(ValueError):
                best = max(best, as_int(row.get("ImageNumber") or 0))
    return best


def compartment_problems(tables, headers):
    """Find what is missing to join the compartments of each cell: a table, or a column that joins them.

    Parameters
    ----------
    tables : dict
        ``{table file name: [(chunk, path), ...]}`` of all chunks.
    headers : dict
        ``{(chunk, path): column names}``.

    Returns
    -------
    list of str
        One message per missing table and per table with missing columns. Empty if the tables are complete.
    """
    by_lower = {name.lower(): name for name in tables}
    missing = [table for table in COMPARTMENT_COLUMNS if table.lower() not in by_lower]
    problems = []
    if missing:
        problems.append(
            f"the merged tables lack {missing}. ExportToSpreadsheet must export Image, Cells, Nuclei and "
            "Cytoplasm, without a file name prefix (the patch step removes the prefix)."
        )

    # A column must be in the table of every chunk. The intersection finds a column that one chunk lacks.
    for table, columns in COMPARTMENT_COLUMNS.items():
        name = by_lower.get(table.lower())
        if not name:
            continue
        common = set.intersection(*(set(headers[key]) for key in tables[name]))
        lacking = [column for column in columns if column not in common]
        if lacking:
            problems.append(
                f"{name} has no column(s) {lacking}. Plate, well and site come from the Metadata module (the "
                "workflow adds the plate). Parent_Cells and Parent_Nuclei come from IdentifyTertiaryObjects."
            )
    return problems


def validate_manifest_row(row, chunk, seen_paths):
    """Check one row of a mask list: the row must be complete, and its mask path safe and unique in the run.

    The chunks of a plate publish their masks into the same <plate>/masks/ folder. If two chunks had the same
    mask path, one mask would replace the other.

    Parameters
    ----------
    row : dict
        One row of a mask_manifest.csv file.
    chunk : str
        The chunk of the row, for example "chunk_0002".
    seen_paths : dict
        ``{mask path: (chunk, ImageNumber, object)}`` of all rows so far. The function adds the row to it.

    Raises
    ------
    SystemExit
        If the row has no mask path or no object, if the path is not safe, or if another row has the
        same path.
    """
    mask_path = row.get("MaskPath", "")
    mask_object = row.get("MaskObject", "")
    if not mask_path or not mask_object:
        sys.exit(f"[merge_features] ERROR: incomplete mask manifest row in {chunk}: {row}")

    # The path is masks/... (no plate) or <plate>/masks/..., relative to the output folder.
    normalized = mask_path.replace("\\", "/")
    parts = normalized.split("/")
    if "masks" not in parts[:2] or normalized.startswith("/") or ".." in parts:
        sys.exit(f"[merge_features] ERROR: unsafe mask path in {chunk}: {mask_path!r}")

    owner = (chunk, row.get("ImageNumber", ""), mask_object)
    if normalized in seen_paths:
        sys.exit(
            f"[merge_features] ERROR: mask path collision for {normalized!r}: "
            f"{seen_paths[normalized]} and {owner}"
        )
    seen_paths[normalized] = owner


def main():
    """Merge each table name over all chunks, and write merge_report.json.

    If a check fails, the function stops the program with an error message.
    """

    # The options come from the MERGE_FEATURES script in main.nf.
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("chunk_dirs", nargs="+", help="features_<chunk> directories")
    ap.add_argument("--outdir", default=".")
    ap.add_argument("--gzip", action="store_true")
    ap.add_argument(
        "--unique-metadata",
        default="",
        help="comma-separated metadata names (e.g. Plate,Well,Site) that must identify one image set",
    )
    ap.add_argument(
        "--require-plate",
        action="store_true",
        help="every row of an image or object table must have a value in Metadata_Plate",
    )
    ap.add_argument(
        "--check-compartments",
        action="store_true",
        help="stop if the Image, Cells, Nuclei or Cytoplasm table, or a column that joins them, is missing",
    )
    args = ap.parse_args()
    set_field_limit()
    os.makedirs(args.outdir, exist_ok=True)

    # Find all tables. Sort the chunks by name (chunk_0001, chunk_0002, ...), so that the merged rows
    # always come in the same order.
    chunks = sorted(args.chunk_dirs, key=chunk_name)
    tables = defaultdict(list)  # table file name -> [(chunk, path)]
    for d in chunks:
        for name in sorted(os.listdir(d)):
            if name.lower().endswith(".csv"):
                tables[name].append((chunk_name(d), os.path.join(d, name)))
    if not tables:
        sys.exit("[merge_features] ERROR: no CSV files found in any chunk.")

    # Offsets that make ImageNumber unique. They come from the per-image tables of each chunk.
    headers = {(c, p): header_of(p) for files in tables.values() for c, p in files}

    # Check the compartment tables before the merge starts: a missing table is found in seconds.
    if args.check_compartments:
        problems = compartment_problems(tables, headers)
        if problems:
            sys.exit("[merge_features] ERROR: " + "\n[merge_features] ERROR: ".join(problems))
    max_img = defaultdict(int)
    for (chunk, path), hdr in headers.items():
        if "ImageNumber" in hdr and "ObjectNumber" not in hdr:
            max_img[chunk] = max(max_img[chunk], max_image_number(path))
    for (chunk, path), hdr in headers.items():  # chunks without an image table (unusual)
        if chunk not in max_img and "ImageNumber" in hdr:
            max_img[chunk] = max(max_img[chunk], max_image_number(path))

    # Each chunk starts after the last image number of all chunks before it.
    offsets, running = {}, 0
    for chunk in [chunk_name(d) for d in chunks]:
        offsets[chunk] = running
        running += max_img.get(chunk, 0)

    summary = {"chunks": len(chunks), "total_image_sets": running, "tables": {}}
    seen_mask_paths = {}

    # --unique-metadata 'Plate,Well' -> ['Metadata_Plate', 'Metadata_Well'].
    unique_columns = [
        name if name.startswith("Metadata_") else f"Metadata_{name}"
        for name in (n.strip() for n in args.unique_metadata.split(","))
        if name
    ]

    # Merge one table name at a time (for example all Nuclei.csv files).
    # The merged table gets all columns of all chunks, in the order in which they first occur.
    # The set makes this fast: a table can have thousands of columns, and a run thousands of chunks.
    for name, files in sorted(tables.items()):
        columns, known = [], set()
        for key in files:
            for column in headers[key]:
                if column not in known:
                    known.add(column)
                    columns.append(column)
        has_img = "ImageNumber" in columns
        out_cols = ["CPNF_Chunk"] + (["CPNF_ChunkImageNumber"] if has_img else []) + columns

        # Each image and object table needs the plate in each row (check_chunk.py adds it).
        needs_plate = args.require_plate and has_img and name != MANIFEST
        if needs_plate and "Metadata_Plate" not in columns:
            sys.exit(f"[merge_features] ERROR: {name} has no column Metadata_Plate.")
        no_plate = 0
        out_name = name + (".gz" if args.gzip else "")
        out_path = os.path.join(args.outdir, out_name)
        opener = (
            (lambda p: gzip.open(p, "wt", newline="", **ENC))
            if args.gzip
            else (lambda p: open(p, "w", newline="", **ENC))
        )
        rows = 0

        # Per-image tables: the same metadata key twice means that the workflow processed a site
        # twice. Causes are the same images given twice, or a plate imaged two times.
        # Joins on these keys would then be wrong. The mask list has one row per mask, so it is not checked.
        is_image_table = has_img and "ObjectNumber" not in columns and name != MANIFEST
        check_keys = bool(unique_columns) and is_image_table and set(unique_columns) <= set(columns)
        seen_keys = {}

        # Copy the rows of each chunk, one row at a time (little memory, also for large object tables).
        # For each row: check the mask path, the metadata key and the plate, then make ImageNumber unique and
        # keep the chunk and the original ImageNumber. A missing column of a chunk stays empty (restval="").
        with opener(out_path) as out:
            writer = csv.DictWriter(out, fieldnames=out_cols, restval="", extrasaction="ignore")
            writer.writeheader()
            for chunk, path in files:
                with open(path, newline="", **ENC) as fh:
                    for row in csv.DictReader(fh):
                        if name == MANIFEST:
                            validate_manifest_row(row, chunk, seen_mask_paths)
                        if check_keys:
                            key = tuple(row.get(column, "") for column in unique_columns)
                            if key in seen_keys:
                                image_set = dict(zip(unique_columns, key))
                                sys.exit(
                                    f"[merge_features] ERROR: {name}: image set {image_set} "
                                    f"appears in {seen_keys[key]} and in {chunk}."
                                )
                            seen_keys[key] = chunk
                        if needs_plate and not (row.get("Metadata_Plate") or "").strip():
                            no_plate += 1
                        row["CPNF_Chunk"] = chunk
                        if has_img:
                            row["CPNF_ChunkImageNumber"] = row.get("ImageNumber", "")
                            try:
                                row["ImageNumber"] = offsets[chunk] + as_int(row["ImageNumber"])
                            except (KeyError, TypeError, ValueError):
                                sys.exit(
                                    f"[merge_features] ERROR: {name} in {chunk}: ImageNumber "
                                    f"{row.get('ImageNumber')!r} is not a number."
                                )
                        writer.writerow(row)
                        rows += 1
        if no_plate:
            sys.exit(f"[merge_features] ERROR: {name}: {no_plate} row(s) have no Metadata_Plate.")
        summary["tables"][out_name] = {"rows": rows, "columns": len(out_cols), "chunks": len(files)}
        print(f"[merge_features] {out_name}: {rows} rows from {len(files)} chunk(s)")

    # merge_report.json: the number of chunks and image sets, and the rows and columns of each table.
    with open(os.path.join(args.outdir, "merge_report.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)


if __name__ == "__main__":
    main()
