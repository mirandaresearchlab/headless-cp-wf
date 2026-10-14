#!/usr/bin/env python3
"""Validate one CellProfiler chunk and build its mask manifest.

The manifest contains one row per image set and mask object, including normalized
paths for every input channel and the actual mask path under the published results.
The command fails on missing, ambiguous, unsafe, or colliding mask mappings.

It runs at the end of each CELLPROFILER job (main.nf), inside the CellProfiler container. CellProfiler
can end with exit code 0 even after errors, so this script is the real test of a job. It does this:
  1. looks in the CellProfiler log for errors while modules ran,
  2. copies the CSV tables into features_<chunk>/ and counts their rows,
  3. checks the image sets: present, the expected number, object counts that agree, required metadata,
  4. connects each mask file to its image set (mask_manifest.csv),
  5. writes qc_<chunk>.json, and stops with exit code 1 if any check failed.

Notes
-----
It uses only the Python standard library, and it must work on Python 3.8 (the container's Python).
Exit codes: 0 = all checks passed, 1 = at least one check failed.
"""

import argparse
import csv
import json
import os
import re
import shutil
import sys
from pathlib import PurePosixPath

# Words that occur in a traceback when CellProfiler fails while it runs a module. A traceback from an
# import at start-up (for example an optional plugin) has none of them and does not count as an error.
RUNTIME_MARKERS = ("run_module", "run_with_yield", "run_image_set", "post_run", "prepare_run")

# The file types that the mask writers can save.
MASK_EXT = {".tif", ".tiff", ".png", ".npy"}

# Metadata columns that hold a path in the job folder. They are left out of the mask list.
TASK_PATH_METADATA = {"Metadata_FileLocation"}


def set_field_limit():
    """Allow very long CSV fields.

    CellProfiler can write long values, and the default limit of the csv module is small.
    """

    # Try the largest limit first. Some systems refuse it, so make it 10 times smaller until it works.
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def runtime_tracebacks(log_text):
    """Return traceback blocks that come from running the pipeline, not from imports.

    Parameters
    ----------
    log_text : str
        The complete CellProfiler log.

    Returns
    -------
    list of str
        Each traceback that names a module-run function (see RUNTIME_MARKERS), cut to
        2,000 characters.
    """
    blocks = re.split(r"(?=Traceback \(most recent call last\))", log_text)
    return [block[:2000] for block in blocks[1:] if any(marker in block for marker in RUNTIME_MARKERS)]


def read_header_and_count(path):
    """Read the column names of a CSV file and count its data rows.

    Parameters
    ----------
    path : str
        Path of the CSV file.

    Returns
    -------
    header : list of str
        The column names (empty for an empty file).
    rows : int
        The number of rows after the header.
    """
    with open(path, newline="", encoding="utf-8", errors="surrogateescape") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])
        return header, sum(1 for _ in reader)


def classify(header):
    """Find the type of a CellProfiler table from its columns.

    Parameters
    ----------
    header : list of str
        The column names of the table.

    Returns
    -------
    str
        "object" for one row per object (ImageNumber and ObjectNumber, for example Nuclei.csv),
        "image" for one row per image set (ImageNumber only, for example Image.csv), or
        "other" (for example Experiment.csv).
    """
    columns = set(header)
    if "ImageNumber" in columns and "ObjectNumber" in columns:
        return "object"
    if "ImageNumber" in columns:
        return "image"
    return "other"


def strip_prefix(value, prefix):
    """Remove a prefix from a text, like str.removeprefix (Python 3.9+).

    The CellProfiler 4.2.8 container ships Python 3.8, which has no str.removeprefix.

    Parameters
    ----------
    value : str
        The text.
    prefix : str
        The prefix to remove.

    Returns
    -------
    str
        The text without the prefix, or the text unchanged if it does not start with the prefix.
    """
    return value[len(prefix) :] if value.startswith(prefix) else value


def safe_relative(path):
    """Return a normalized relative POSIX path, rejecting traversal and absolute paths.

    Parameters
    ----------
    path : str or os.PathLike
        The path to check. Backslashes count as folder separators.

    Returns
    -------
    str
        The path with "/" separators and without a leading "./" ("" for "" or ".").

    Raises
    ------
    ValueError
        If the path is absolute or contains "..".
    """
    normalized = str(path).replace("\\", "/").strip()
    if normalized in {"", "."}:
        return ""
    value = PurePosixPath(normalized)
    if value.is_absolute() or ".." in value.parts:
        raise ValueError(f"unsafe path outside the input/output root: {path!r}")
    return strip_prefix(value.as_posix(), "./")


def relative_channel_dir(path_name, input_dir):
    """Normalize CellProfiler's task-local PathName_* value relative to input_dir.

    CellProfiler writes the full folder of each image, for example /work/ab/12.../input/plate1.
    The mask list needs only the part below the image folder: plate1.

    Parameters
    ----------
    path_name : str
        The value of a PathName_<channel> column.
    input_dir : str
        The staged image folder of the job ($PWD/input).

    Returns
    -------
    str
        The folder relative to the image folder ("" for the image folder itself).

    Raises
    ------
    ValueError
        If the folder is not below the image folder, or is unsafe (see safe_relative).
    """
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
    """Find all mask files below a folder.

    Parameters
    ----------
    mask_root : str
        The masks/ folder of the CellProfiler output.

    Returns
    -------
    list of str
        The paths relative to mask_root, with "/" separators, for example
        "plate1/a_Nuclei_mask.tiff". Empty if the folder does not exist.
    """
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
    """Write a mask list with only its column names (no masks in this run).

    Parameters
    ----------
    manifest : str
        Path of the mask_manifest.csv file to write.
    """
    with open(manifest, "w", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=["ImageNumber", "MaskObject", "MaskPath"]).writeheader()


def build_mask_manifest(image_csv, report, mask_root, input_dir, manifest, errors, warnings):
    """Map injected masks to image rows and fail closed on incomplete mappings.

    For each image set and each object type, the expected mask name is
    <folder of the reference image>/<reference image name><suffix>, for example
    plate1/site1_DNA_Nuclei_mask.tiff. Each expected mask must exist exactly once, and no two
    image sets may share a mask.

    Parameters
    ----------
    image_csv : str
        The per-image table of the chunk.
    report : dict
        The patch report (patch_report.json): the mask writers and the reference image.
    mask_root : str
        The masks/ folder of the CellProfiler output.
    input_dir : str
        The staged image folder of the job.
    manifest : str
        Path of the mask_manifest.csv file to write.
    errors : list of str
        Problems that stop the job are added to this list.
    warnings : list of str
        Problems that only need attention are added to this list.

    Returns
    -------
    manifest_rows : int
        The number of rows written to the mask list.
    mask_files : int
        The number of mask files found below mask_root.
    """

    # The mask writers that the patch step added (from patch_report.json).
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

    # Choose the columns of the mask list: ImageNumber, the metadata, three columns per channel
    # (file name, folder, path in input_dir), and the mask object and path.
    file_columns = [column for column in source_columns if column.startswith("FileName_")]

    # Metadata_FileLocation is a file: URL inside the task work directory: not portable.
    metadata_columns = [
        column
        for column in source_columns
        if column.startswith("Metadata_") and column not in TASK_PATH_METADATA
    ]
    channel_columns = []
    for file_column in file_columns:
        channel = strip_prefix(file_column, "FileName_")
        channel_columns.extend([file_column, f"PathName_{channel}", f"InputPath_{channel}"])
    output_columns = ["ImageNumber", *metadata_columns, *channel_columns, "MaskObject", "MaskPath"]

    actual_masks = find_mask_files(mask_root)
    used_paths = {}
    image_numbers = set()
    manifest_rows = []

    # One pass over the image sets. Each image number must be present and unique.
    for image_row in image_rows:
        image_number = image_row.get("ImageNumber", "")
        if not image_number:
            errors.append("Per-image table contains a row without ImageNumber.")
            continue
        if image_number in image_numbers:
            errors.append(f"Per-image table contains duplicate ImageNumber {image_number!r}.")
            continue
        image_numbers.add(image_number)

        # Make the input path of each channel relative to input_dir. An unsafe path skips the image set.
        channel_values = {}
        invalid_channel = False
        for file_column in file_columns:
            channel = strip_prefix(file_column, "FileName_")
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

        # The masks are named after the reference image, so its path decides the expected mask names.
        reference_path = channel_values.get(f"InputPath_{reference_image}", "")
        if not reference_path:
            errors.append(
                f"ImageNumber {image_number} has no input path for reference channel {reference_image!r}."
            )
            continue
        reference = PurePosixPath(reference_path)

        # Find the mask file of each object type: same folder, name = reference name + suffix,
        # any mask extension. Exactly one file must match.
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

            # Two image sets with the same mask file would mean that one mask is lost: refuse it.
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

    # Mask-like files that no image set claims: probably saved by the user's own SaveImages. Only warn.
    unused_masks = sorted(set(actual_masks) - {strip_prefix(path, "masks/") for path in used_paths})
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


def check_object_counts(features_dir, image_name, tables, errors, warnings):
    """Check that Count_<Object> in the per-image table equals the rows of <prefix><Object>.csv.

    ExportToSpreadsheet names tables <prefix>Image.csv and <prefix><Object>.csv, so the
    prefix comes from the image table name. Objects without their own table are skipped.

    Parameters
    ----------
    features_dir : str
        The folder with the copied tables of the chunk.
    image_name : str
        File name of the per-image table, for example "MyExpt_Image.csv".
    tables : dict
        ``{file name: {"kind": ..., "rows": ..., "columns": ...}}`` for all tables of the chunk.
    errors : list of str
        A count that does not agree, or a column with text values, is added to this list.
    warnings : list of str
        Image sets without objects are reported in this list.

    Returns
    -------
    dict
        ``{object name: number of image sets with zero objects}``.
    """
    prefix = image_name[: -len("Image.csv")] if image_name.endswith("Image.csv") else None
    if prefix is None:
        return {}
    with open(
        os.path.join(features_dir, image_name), newline="", encoding="utf-8", errors="surrogateescape"
    ) as fh:
        rows = list(csv.DictReader(fh))
    empty_images = {}

    # Each Count_<Object> column of the image table: add the counts of all image sets and compare
    # the sum with the number of rows in the object table.
    for column in rows[0].keys() if rows else []:
        if not column.startswith("Count_"):
            continue
        object_name = strip_prefix(column, "Count_")
        table = f"{prefix}{object_name}.csv"
        try:
            counts = [int(float(row[column])) for row in rows]
        except (TypeError, ValueError):
            errors.append(f"{image_name}: column {column} has non-numeric values.")
            continue
        empty_images[object_name] = sum(1 for count in counts if count == 0)
        if table in tables and tables[table]["kind"] == "object" and tables[table]["rows"] != sum(counts):
            errors.append(
                f"{image_name} counts {sum(counts)} {object_name} objects but {table} has "
                f"{tables[table]['rows']} rows: the export is incomplete or inconsistent."
            )

    # Images without objects are allowed (for example an empty well), but the user should know.
    for object_name, empty in empty_images.items():
        if empty:
            warnings.append(
                f"{empty} of {len(rows)} image set(s) have no {object_name} objects "
                "(empty field, out of focus, or a segmentation failure?)."
            )
    return empty_images


def metadata_columns_from(spec):
    """Turn metadata names into column names.

    Parameters
    ----------
    spec : str or None
        Comma-separated names, for example "Plate,Well,Metadata_Site".

    Returns
    -------
    list of str
        For example ["Metadata_Plate", "Metadata_Well", "Metadata_Site"].
    """
    names = [name.strip() for name in (spec or "").split(",") if name.strip()]
    return [name if name.startswith("Metadata_") else f"Metadata_{name}" for name in names]


def check_required_metadata(path, columns, errors):
    """Check that every image row has a non-empty, unique value for each required metadata column.

    Parameters
    ----------
    path : str
        The per-image table.
    columns : list of str
        The required columns, for example ["Metadata_Plate", "Metadata_Well"].
    errors : list of str
        Missing columns, empty values and duplicate keys are added to this list.
    """
    with open(path, newline="", encoding="utf-8", errors="surrogateescape") as handle:
        reader = csv.DictReader(handle)

        # A missing column means that the Metadata module of the pipeline does not make this value.
        missing = [column for column in columns if column not in (reader.fieldnames or [])]
        if missing:
            errors.append(
                f"{os.path.basename(path)} has no column(s) {missing} required by --required_metadata. "
                "Extract them with the Metadata module of your pipeline."
            )
            return

        # Collect the image sets with an empty value, and the keys that occur more than once.
        empty, seen, duplicates = [], set(), []
        for row in reader:
            key = tuple(row[column] for column in columns)
            if any(value.strip() == "" for value in key):
                empty.append(row.get("ImageNumber", "?"))
            elif key in seen:
                duplicates.append(key)
            seen.add(key)
    if empty:
        errors.append(
            f"{len(empty)} image set(s) in {os.path.basename(path)} have empty {columns}, "
            f"e.g. ImageNumber {empty[:3]}. Check the Metadata regular expression."
        )
    if duplicates:
        errors.append(f"{len(duplicates)} duplicate {columns} key(s) in one chunk, e.g. {duplicates[:3]}.")


def main():
    """Run all checks on one chunk.

    The function ends the program with exit code 1 if at least one check failed.
    """

    # The options come from the CELLPROFILER script in main.nf.
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
    parser.add_argument(
        "--required-metadata", default="", help="comma-separated metadata names, e.g. Plate,Well,Site"
    )
    args = parser.parse_args()
    set_field_limit()

    # Errors stop the job. Warnings go only into the log and into qc_<chunk>.json.
    errors, warnings = [], []

    # Step 1: errors that CellProfiler wrote into its log while it ran the modules.
    with open(args.log, encoding="utf-8", errors="replace") as handle:
        log_text = handle.read()
    tracebacks = runtime_tracebacks(log_text)
    if tracebacks:
        errors.append(f"{len(tracebacks)} traceback(s) raised while running modules; first:\n{tracebacks[0]}")

    # Step 2: copy each CSV table into features_<chunk>/ and note its type and size. A table in a
    # sub-folder gets the folder in its name ("sub__table.csv"), so that names stay unique.
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

    # Step 3: CellProfiler must have made an image table with at least one image set.
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

    # The object counts must agree with the object tables.
    images_without_objects = {}
    for name in image_tables:
        images_without_objects.update(check_object_counts(args.features_dir, name, tables, errors, warnings))

    # With --required_metadata: each image set needs these values, and they must be unique.
    required = metadata_columns_from(args.required_metadata)
    if required:
        for name in image_tables:
            check_required_metadata(os.path.join(args.features_dir, name), required, errors)

    # The number of image sets must be the number that the workflow predicted. A difference means
    # that CellProfiler grouped the files differently, for example because a chunk split a site.
    if args.expected_sets > 0 and image_sets and image_sets != args.expected_sets:
        message = (
            f"CellProfiler processed {image_sets} image sets but the workflow predicted "
            f"{args.expected_sets} (from --group_regex, or one per file without it). --group_regex may "
            "not match how NamesAndTypes builds image sets, so channels of one site could have been "
            "split across chunks. Set --strict_image_count false only after you checked the image sets."
        )
        (errors if args.strict else warnings).append(message)

    # Step 4: the masks. Each image set needs one mask per object type that the patch step added.
    with open(args.patch_report, encoding="utf-8") as handle:
        patch_report = json.load(handle)
    managed_masks = patch_report.get("masks_managed", patch_report.get("masks_added", []))
    expected_masks = image_sets * len(managed_masks)
    mask_root = os.path.join(args.outdir, "masks")
    manifest_rows = 0
    mask_count = len(find_mask_files(mask_root))

    # The mask list needs the image table with the columns of the reference channel. There must be
    # exactly one such table.
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

    # Step 5: write all results of the checks to qc_<chunk>.json. The workflow publishes it in logs/.
    qc = {
        "outdir": args.outdir,
        "image_sets": image_sets,
        "expected_image_sets": args.expected_sets,
        "mask_files": mask_count,
        "expected_mask_files": expected_masks,
        "mask_manifest_rows": manifest_rows,
        "images_without_objects": images_without_objects,
        "tables": tables,
        "warnings": warnings,
        "errors": errors,
    }
    with open(args.qc, "w", encoding="utf-8") as handle:
        json.dump(qc, handle, indent=2)

    # Show the warnings. On errors, also show the end of the CellProfiler log, then stop the job.
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
