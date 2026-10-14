#!/usr/bin/env python3
"""Merge the tables of all chunks into one table per name.

CellProfiler starts ImageNumber at 1 in each chunk. If you only put the tables one after the other,
objects of different images get the same ImageNumber. Thus each merged table gets two columns in front:
  CPNF_Chunk             - the chunk of the row.
  CPNF_GlobalImageNumber - an image number that is unique in the run. It has the same value in the
                           per-image and the per-object tables. Thus you can join the tables on it.

The merged table has all columns of all chunks. A value that a chunk does not have stays empty. The
script reads and writes one row at a time, with only the Python standard library. Thus it works on large
object tables and with any python3.

The merge also stops the run in two cases. In the first case, two chunks wrote the same mask file.
In the second case (with --unique-metadata), the same plate, well and site occur in two chunks.

Examples
--------
chunk_0001 has image sets 1-150, and chunk_0002 has image sets 1-150. In the merged tables,
image set 1 of chunk_0002 gets CPNF_GlobalImageNumber 151.
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


def validate_manifest_row(row, chunk, seen_paths):
    """Check one row of a mask list: the row must be complete, and its mask path safe and unique in the run.

    All chunks publish their masks into the same results/masks/ folder. If two chunks had the same
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
    normalized = mask_path.replace("\\", "/")
    if not normalized.startswith("masks/") or normalized.startswith("/") or ".." in normalized.split("/"):
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

    # Merge one table name at a time (for example all MyExpt_Nuclei.csv files).
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
        out_cols = ["CPNF_Chunk"] + (["CPNF_GlobalImageNumber"] if has_img else []) + columns
        out_name = name + (".gz" if args.gzip else "")
        out_path = os.path.join(args.outdir, out_name)
        opener = (
            (lambda p: gzip.open(p, "wt", newline="", **ENC))
            if args.gzip
            else (lambda p: open(p, "w", newline="", **ENC))
        )
        rows = 0

        # Per-image tables: the same metadata key in two chunks means that the workflow processed a site
        # twice. Causes are the same images given twice, or a plate imaged two times.
        # Joins on these keys would then be wrong.
        is_image_table = has_img and "ObjectNumber" not in columns
        check_keys = bool(unique_columns) and is_image_table and set(unique_columns) <= set(columns)
        seen_keys = {}

        # Copy the rows of each chunk, one row at a time (little memory, also for large object tables).
        # For each row: check the mask path and the metadata key, then add the two CPNF_ columns.
        # A missing column of a chunk stays empty (restval="").
        with opener(out_path) as out:
            writer = csv.DictWriter(out, fieldnames=out_cols, restval="", extrasaction="ignore")
            writer.writeheader()
            for chunk, path in files:
                with open(path, newline="", **ENC) as fh:
                    for row in csv.DictReader(fh):
                        if name == "mask_manifest.csv":
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
                        row["CPNF_Chunk"] = chunk
                        if has_img:
                            try:
                                row["CPNF_GlobalImageNumber"] = offsets[chunk] + as_int(row["ImageNumber"])
                            except (KeyError, TypeError, ValueError):
                                row["CPNF_GlobalImageNumber"] = ""
                        writer.writerow(row)
                        rows += 1
        summary["tables"][out_name] = {"rows": rows, "columns": len(out_cols), "chunks": len(files)}
        print(f"[merge_features] {out_name}: {rows} rows from {len(files)} chunk(s)")

    # merge_report.json: the number of chunks and image sets, and the rows and columns of each table.
    with open(os.path.join(args.outdir, "merge_report.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)


if __name__ == "__main__":
    main()
