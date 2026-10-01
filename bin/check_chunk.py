#!/usr/bin/env python3
"""Validate one CellProfiler chunk and build its mask manifest.

The manifest contains one row per image set and mask object, including normalized
paths for every input channel and the actual mask path under the published results.
The command fails on missing, ambiguous, unsafe, or colliding mask mappings.
"""

import argparse
import csv
import json
import os
import re
import shutil
import sys
from pathlib import PurePosixPath

RUNTIME_MARKERS = ("run_module", "run_with_yield", "run_image_set", "post_run", "prepare_run")
MASK_EXT = {".tif", ".tiff", ".png", ".npy"}


def set_field_limit():
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def runtime_tracebacks(log_text):
    """Return traceback blocks that come from running the pipeline, not from imports."""
    blocks = re.split(r"(?=Traceback \(most recent call last\))", log_text)
    return [block[:2000] for block in blocks[1:] if any(marker in block for marker in RUNTIME_MARKERS)]


def read_header_and_count(path):
    with open(path, newline="", encoding="utf-8", errors="surrogateescape") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])
        return header, sum(1 for _ in reader)


def classify(header):
    columns = set(header)
    if "ImageNumber" in columns and "ObjectNumber" in columns:
        return "object"
    if "ImageNumber" in columns:
        return "image"
    return "other"


def safe_relative(path):
    """Return a normalized relative POSIX path, rejecting traversal and absolute paths."""
    normalized = str(path).replace("\\", "/").strip()
    if normalized in {"", "."}:
        return ""
    value = PurePosixPath(normalized)
    if value.is_absolute() or ".." in value.parts:
        raise ValueError(f"unsafe path outside the input/output root: {path!r}")
    return value.as_posix().removeprefix("./")


def relative_channel_dir(path_name, input_dir):
    """Normalize CellProfiler's task-local PathName_* value relative to input_dir."""
    value = str(path_name or "").replace("\\", "/").rstrip("/")
    root = str(input_dir).replace("\\", "/").rstrip("/")
    if not value or value == root:
        return ""
    if not PurePosixPath(value).is_absolute():
        return safe_relative(value)
    if value.startswith(f"{root}/"):
        return safe_relative(value[len(root) + 1 :])

    # Containers can rewrite the work-directory prefix, but the staged input
    # directory remains named "input".
    marker = "/input/"
    if marker in value:
        return safe_relative(value.rsplit(marker, 1)[1])
    if value.endswith("/input"):
        return ""
    raise ValueError(f"channel directory is not below the staged input root: {path_name!r}")


def find_mask_files(mask_root):
    found = []
    if not os.path.isdir(mask_root):
        return found
    for root, _dirs, files in os.walk(mask_root):
        for name in sorted(files):
            if os.path.splitext(name)[1].lower() in MASK_EXT:
                relative = os.path.relpath(os.path.join(root, name), mask_root)
                found.append(PurePosixPath(relative).as_posix())
    return found


def write_empty_manifest(manifest):
    with open(manifest, "w", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=["ImageNumber", "MaskObject", "MaskPath"]).writeheader()


def build_mask_manifest(image_csv, report, mask_root, input_dir, manifest, errors, warnings):
    """Map injected masks to image rows and fail closed on incomplete mappings."""
    masks = report.get("masks_managed", report.get("masks_added", []))
    if not masks:
        write_empty_manifest(manifest)
        return 0, len(find_mask_files(mask_root))

    reference_image = report.get("mask_reference_image")
    if not reference_image:
        errors.append("Patch report has managed masks but no mask_reference_image.")
        write_empty_manifest(manifest)
        return 0, len(find_mask_files(mask_root))

    with open(image_csv, newline="", encoding="utf-8", errors="surrogateescape") as handle:
        reader = csv.DictReader(handle)
        source_columns = reader.fieldnames or []
        image_rows = list(reader)

    file_columns = [column for column in source_columns if column.startswith("FileName_")]
    metadata_columns = [column for column in source_columns if column.startswith("Metadata_")]
    channel_columns = []
    for file_column in file_columns:
        channel = file_column.removeprefix("FileName_")
        channel_columns.extend([file_column, f"PathName_{channel}", f"InputPath_{channel}"])
    output_columns = ["ImageNumber", *metadata_columns, *channel_columns, "MaskObject", "MaskPath"]

    actual_masks = find_mask_files(mask_root)
    used_paths = {}
    image_numbers = set()
    manifest_rows = []

    for image_row in image_rows:
        image_number = image_row.get("ImageNumber", "")
        if not image_number:
            errors.append("Per-image table contains a row without ImageNumber.")
            continue
        if image_number in image_numbers:
            errors.append(f"Per-image table contains duplicate ImageNumber {image_number!r}.")
            continue
        image_numbers.add(image_number)

        channel_values = {}
        invalid_channel = False
        for file_column in file_columns:
            channel = file_column.removeprefix("FileName_")
            path_column = f"PathName_{channel}"
            filename = image_row.get(file_column, "")
            try:
                relative_dir = relative_channel_dir(image_row.get(path_column, ""), input_dir)
                input_path = safe_relative(PurePosixPath(relative_dir, filename)) if filename else ""
            except ValueError as exc:
                errors.append(f"ImageNumber {image_number}, channel {channel}: {exc}")
                invalid_channel = True
                break
            channel_values[file_column] = filename
            channel_values[path_column] = relative_dir
            channel_values[f"InputPath_{channel}"] = input_path
        if invalid_channel:
            continue

        reference_path = channel_values.get(f"InputPath_{reference_image}", "")
        if not reference_path:
            errors.append(
                f"ImageNumber {image_number} has no input path for reference channel {reference_image!r}."
            )
            continue
        reference = PurePosixPath(reference_path)

        for mask in masks:
            object_name = mask.get("object", "")
            suffix = mask.get("suffix", f"_{object_name}_mask")
            expected_stem = f"{reference.stem}{suffix}"
            candidates = [
                path
                for path in actual_masks
                if PurePosixPath(path).parent == reference.parent
                and PurePosixPath(path).stem == expected_stem
            ]
            if not candidates:
                expected = reference.parent / expected_stem
                errors.append(
                    f"Missing {object_name!r} mask for ImageNumber {image_number}: expected "
                    f"masks/{expected}.[tif|tiff|png|npy]"
                )
                continue
            if len(candidates) > 1:
                errors.append(
                    f"Ambiguous {object_name!r} mask for ImageNumber {image_number}: "
                    f"{[f'masks/{path}' for path in candidates]}"
                )
                continue

            mask_path = f"masks/{candidates[0]}"
            owner = (image_number, object_name)
            if mask_path in used_paths:
                errors.append(
                    f"Mask path collision: {mask_path!r} maps to both {used_paths[mask_path]} and {owner}."
                )
                continue
            used_paths[mask_path] = owner
            manifest_rows.append(
                {
                    "ImageNumber": image_number,
                    **{column: image_row.get(column, "") for column in metadata_columns},
                    **channel_values,
                    "MaskObject": object_name,
                    "MaskPath": mask_path,
                }
            )

    unused_masks = sorted(set(actual_masks) - {path.removeprefix("masks/") for path in used_paths})
    if unused_masks:
        warnings.append(
            f"Found {len(unused_masks)} mask-like file(s) not mapped by the injected mask writers; "
            f"they are excluded from mask_manifest.csv, e.g. {unused_masks[:3]}."
        )

    with open(manifest, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=output_columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(manifest_rows)
    return len(manifest_rows), len(actual_masks)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--outdir", required=True, help="CellProfiler output folder (-o)")
    parser.add_argument("--log", required=True)
    parser.add_argument("--patch-report", required=True)
    parser.add_argument("--expected-sets", type=int, default=-1, help="-1 = unknown")
    parser.add_argument("--input-dir", required=True, help="staged CellProfiler input root")
    parser.add_argument("--features-dir", required=True)
    parser.add_argument("--manifest", required=True, help="per-chunk mask manifest CSV to write")
    parser.add_argument("--qc", required=True, help="QC JSON to write")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    set_field_limit()

    errors, warnings = [], []
    with open(args.log, encoding="utf-8", errors="replace") as handle:
        log_text = handle.read()
    tracebacks = runtime_tracebacks(log_text)
    if tracebacks:
        errors.append(f"{len(tracebacks)} traceback(s) raised while running modules; first:\n{tracebacks[0]}")

    os.makedirs(args.features_dir, exist_ok=True)
    tables = {}
    for root, _dirs, files in os.walk(args.outdir):
        for name in sorted(files):
            if not name.lower().endswith(".csv"):
                continue
            source = os.path.join(root, name)
            relative = os.path.relpath(source, args.outdir)
            destination = relative.replace(os.sep, "__")
            if destination == "mask_manifest.csv":
                errors.append("CellProfiler produced reserved output name 'mask_manifest.csv'.")
                continue
            shutil.copyfile(source, os.path.join(args.features_dir, destination))
            header, rows = read_header_and_count(source)
            tables[destination] = {"kind": classify(header), "rows": rows, "columns": len(header)}

    image_tables = {name: data for name, data in tables.items() if data["kind"] == "image"}
    image_sets = max((data["rows"] for data in image_tables.values()), default=0)
    if not tables:
        errors.append("CellProfiler wrote no CSV files (no ExportToSpreadsheet output).")
    elif not image_tables:
        errors.append("No per-image table found (a CSV with ImageNumber but no ObjectNumber).")
    elif image_sets == 0:
        errors.append(
            "Per-image table is empty: zero image sets were processed. "
            "Check the Images/NamesAndTypes filters against your file names."
        )

    if args.expected_sets > 0 and image_sets and image_sets != args.expected_sets:
        message = (
            f"CellProfiler processed {image_sets} image sets but --group_regex predicted "
            f"{args.expected_sets}. The regex may not match how NamesAndTypes builds image sets, "
            "so channels of one site could have been split across chunks."
        )
        (errors if args.strict else warnings).append(message)

    with open(args.patch_report, encoding="utf-8") as handle:
        patch_report = json.load(handle)
    managed_masks = patch_report.get("masks_managed", patch_report.get("masks_added", []))
    expected_masks = image_sets * len(managed_masks)
    mask_root = os.path.join(args.outdir, "masks")
    manifest_rows = 0
    mask_count = len(find_mask_files(mask_root))

    if managed_masks:
        reference_image = patch_report.get("mask_reference_image")
        required = {"ImageNumber", f"FileName_{reference_image}", f"PathName_{reference_image}"}
        candidates = [
            name
            for name in image_tables
            if required <= set(read_header_and_count(os.path.join(args.features_dir, name))[0])
        ]
        if len(candidates) != 1:
            errors.append(
                "Expected exactly one per-image table containing the mask reference channel columns; "
                f"found {candidates or 'none'}."
            )
            write_empty_manifest(args.manifest)
        else:
            manifest_rows, mask_count = build_mask_manifest(
                os.path.join(args.features_dir, candidates[0]),
                patch_report,
                mask_root,
                args.input_dir,
                args.manifest,
                errors,
                warnings,
            )
    else:
        write_empty_manifest(args.manifest)

    if manifest_rows != expected_masks:
        errors.append(
            f"Mask manifest has {manifest_rows} rows but expected {expected_masks} "
            f"({image_sets} image sets x {len(managed_masks)} objects)."
        )

    qc = {
        "outdir": args.outdir,
        "image_sets": image_sets,
        "expected_image_sets": args.expected_sets,
        "mask_files": mask_count,
        "expected_mask_files": expected_masks,
        "mask_manifest_rows": manifest_rows,
        "tables": tables,
        "warnings": warnings,
        "errors": errors,
    }
    with open(args.qc, "w", encoding="utf-8") as handle:
        json.dump(qc, handle, indent=2)

    for warning in warnings:
        print(f"[check_chunk] WARNING: {warning}", file=sys.stderr)
    if errors:
        for error in errors:
            print(f"[check_chunk] ERROR: {error}", file=sys.stderr)
        print("\n----- last 40 lines of the CellProfiler log -----", file=sys.stderr)
        print("\n".join(log_text.splitlines()[-40:]), file=sys.stderr)
        sys.exit(1)
    print(
        f"[check_chunk] OK: {image_sets} image sets, {len(tables)} tables, "
        f"{mask_count} mask files, {manifest_rows} manifest rows"
    )


if __name__ == "__main__":
    main()
