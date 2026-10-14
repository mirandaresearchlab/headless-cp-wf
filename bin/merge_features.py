#!/usr/bin/env python3
"""
Merge per-chunk CellProfiler ExportToSpreadsheet tables into one table per name.

ImageNumber restarts at 1 in every chunk, so naive concatenation silently mixes up
objects from different images. Every merged table therefore gets two leading columns:
  CPNF_Chunk             - which chunk the row came from
  CPNF_GlobalImageNumber - ImageNumber made unique across chunks (same value in the
                           per-image and per-object tables, so you can join on it)
Columns are unioned across chunks (missing values left empty). Streams row by row,
standard library only, so it works on large object tables and in any python3.
"""

import argparse
import contextlib
import csv
import gzip
import json
import os
import sys
from collections import defaultdict

ENC = dict(encoding="utf-8", errors="surrogateescape")


def set_field_limit():
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def chunk_name(path):
    base = os.path.basename(os.path.normpath(path))
    return base[len("features_") :] if base.startswith("features_") else base


def as_int(value):
    """CellProfiler sometimes writes integers as '3.0'."""
    return int(float(value))


def header_of(path):
    with open(path, newline="", **ENC) as fh:
        return next(csv.reader(fh), [])


def max_image_number(path):
    best = 0
    with open(path, newline="", **ENC) as fh:
        for row in csv.DictReader(fh):
            with contextlib.suppress(ValueError):
                best = max(best, as_int(row.get("ImageNumber") or 0))
    return best


def validate_manifest_row(row, chunk, seen_paths):
    """Reject incomplete, unsafe, or globally colliding published mask paths."""
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

    chunks = sorted(args.chunk_dirs, key=chunk_name)
    tables = defaultdict(list)  # table file name -> [(chunk, path)]
    for d in chunks:
        for name in sorted(os.listdir(d)):
            if name.lower().endswith(".csv"):
                tables[name].append((chunk_name(d), os.path.join(d, name)))
    if not tables:
        sys.exit("[merge_features] ERROR: no CSV files found in any chunk.")

    # Offsets that make ImageNumber unique: taken from the per-image table(s) of each chunk.
    headers = {(c, p): header_of(p) for files in tables.values() for c, p in files}
    max_img = defaultdict(int)
    for (chunk, path), hdr in headers.items():
        if "ImageNumber" in hdr and "ObjectNumber" not in hdr:
            max_img[chunk] = max(max_img[chunk], max_image_number(path))
    for (chunk, path), hdr in headers.items():  # chunks without an image table (unusual)
        if chunk not in max_img and "ImageNumber" in hdr:
            max_img[chunk] = max(max_img[chunk], max_image_number(path))
    offsets, running = {}, 0
    for chunk in [chunk_name(d) for d in chunks]:
        offsets[chunk] = running
        running += max_img.get(chunk, 0)

    summary = {"chunks": len(chunks), "total_image_sets": running, "tables": {}}
    seen_mask_paths = {}
    unique_columns = [
        name if name.startswith("Metadata_") else f"Metadata_{name}"
        for name in (n.strip() for n in args.unique_metadata.split(","))
        if name
    ]
    for name, files in sorted(tables.items()):
        # Union of columns in first-seen order. A set keeps this linear: tables can have
        # thousands of features and runs thousands of chunks.
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
        # Per-image tables: the same metadata key in two chunks means one site was processed twice
        # (overlapping inputs, re-imaged plates). Joins on these keys downstream would then be wrong.
        is_image_table = has_img and "ObjectNumber" not in columns
        check_keys = bool(unique_columns) and is_image_table and set(unique_columns) <= set(columns)
        seen_keys = {}
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

    with open(os.path.join(args.outdir, "merge_report.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)


if __name__ == "__main__":
    main()
