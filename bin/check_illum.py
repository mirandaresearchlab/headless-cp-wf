#!/usr/bin/env python3
"""Check the illumination functions of one plate (one ILLUM job), and copy them to one folder.

The script runs at the end of each ILLUM job (main.nf), in the CellProfiler container. The illumination
pipeline calculates one function per channel from all images of the plate and saves it as a .npy file. The
analysis chunks divide each image by its function. Thus a missing, infinite or zero value would give wrong
features without any error. This script does these steps:
  1. It looks in the CellProfiler log for errors while the modules ran.
  2. It finds all .npy files in the CellProfiler output folder. Their number must be the number of SaveImages
     modules that save .npy files (from the patch report).
  3. It reads each file and checks that all values are finite and greater than 0.
  4. It copies the files into one folder (--dest) and writes a QC file. It stops with exit code 1 if a
     check failed.

Notes
-----
The script uses only the Python standard library (no numpy). It must work on Python 3.8 (the Python of the
container). Exit codes: 0 = all checks passed, 1 = at least one check failed.
"""

import argparse
import ast
import json
import math
import os
import shutil
import struct
import sys
from array import array

from check_chunk import runtime_tracebacks

# The numpy types of an illumination function, and the matching array typecodes of the standard library.
# CellProfiler saves the functions as floating point numbers. Integers are allowed for completeness.
TYPECODES = {"f4": "f", "f8": "d", "u1": "B", "u2": "H", "u4": "I", "i1": "b", "i2": "h", "i4": "i"}


def read_npy(path):
    """Read a .npy file without numpy.

    Parameters
    ----------
    path : str
        Path of the .npy file (format version 1, 2 or 3, not an object array).

    Returns
    -------
    shape : list of int
        The shape of the array, for example [2500, 2500].
    values : array.array
        All values of the array (order does not matter for the checks).

    Raises
    ------
    ValueError
        If the file is not a .npy file, or has a type that this function cannot read.
    """
    with open(path, "rb") as handle:
        if handle.read(6) != b"\x93NUMPY":
            raise ValueError("not a .npy file")
        major = handle.read(2)[0]
        size_format = "<H" if major == 1 else "<I"
        header_size = struct.unpack(size_format, handle.read(struct.calcsize(size_format)))[0]
        header = ast.literal_eval(handle.read(header_size).decode("latin1"))
        data = handle.read()

    # descr is for example '<f8': byte order (<, >, | or =), kind (f, u, i) and size in bytes.
    descr = header["descr"]
    order, code = (descr[0], descr[1:]) if descr[0] in "<>|=" else ("=", descr)
    if code not in TYPECODES:
        raise ValueError(f"unsupported type {descr!r}")
    values = array(TYPECODES[code])
    if values.itemsize != int(code[1:]):
        raise ValueError(f"type {descr!r} has another size on this computer")
    values.frombytes(data[: len(data) - len(data) % values.itemsize])

    # "<" = little endian, ">" = big endian, "|" and "=" = no order or the order of this computer.
    if (order == ">" and sys.byteorder == "little") or (order == "<" and sys.byteorder == "big"):
        values.byteswap()
    shape = [int(n) for n in header["shape"]]
    expected = math.prod(shape) if shape else 1
    if len(values) != expected:
        raise ValueError(f"has {len(values)} values, but its shape {shape} needs {expected}")
    return shape, values


def check_function(path, errors):
    """Read one illumination function and check its values.

    Parameters
    ----------
    path : str
        Path of the .npy file.
    errors : list of str
        The function adds each problem that stops the job to this list.

    Returns
    -------
    dict
        The shape, the minimum, the maximum and the mean, for the QC file. Empty if the file is not readable.
    """
    name = os.path.basename(path)
    try:
        shape, values = read_npy(path)
    except (OSError, ValueError, SyntaxError, KeyError) as exc:
        errors.append(f"{name}: cannot read the file: {exc}")
        return {}

    # Dividing an image by a function with NaN, an infinite value or a value <= 0 gives wrong intensities.
    finite = [value for value in values if math.isfinite(value)]
    if len(finite) != len(values):
        errors.append(f"{name}: {len(values) - len(finite)} value(s) are not finite (NaN or infinite).")
    if not finite:
        return {"shape": shape}
    smallest = min(finite)
    if smallest <= 0:
        errors.append(f"{name}: minimum {smallest} is not > 0. Images would be divided by zero or less.")
    return {"shape": shape, "min": smallest, "max": max(finite), "mean": sum(finite) / len(finite)}


def main():
    """Run all checks on the output of one ILLUM job.

    If at least one check failed, the function stops the program with exit code 1.
    """

    # The options come from the ILLUM script in main.nf.
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--outdir", required=True, help="CellProfiler output folder (-o)")
    parser.add_argument("--log", required=True)
    parser.add_argument("--patch-report", required=True, help="patch report of the illumination pipeline")
    parser.add_argument("--dest", required=True, help="folder to copy the checked .npy files into")
    parser.add_argument("--qc", required=True, help="QC JSON to write")
    parser.add_argument("--channels", type=int, default=0, help="files per image set (0 = unknown)")
    args = parser.parse_args()
    errors, warnings = [], []

    # Step 1: errors that CellProfiler wrote into its log while it ran the modules.
    with open(args.log, encoding="utf-8", errors="replace") as handle:
        log_text = handle.read()
    tracebacks = runtime_tracebacks(log_text)
    if tracebacks:
        errors.append(f"{len(tracebacks)} traceback(s) raised while running modules; first:\n{tracebacks[0]}")

    # Step 2: one .npy file for each SaveImages module that saves one (patch_cppipe.py --illum lists them).
    with open(args.patch_report, encoding="utf-8") as handle:
        expected = len(json.load(handle).get("illum_outputs", []))
    found = []
    for root, _dirs, files in os.walk(args.outdir):
        found += [os.path.join(root, name) for name in sorted(files) if name.lower().endswith(".npy")]
    if len(found) != expected:
        errors.append(
            f"found {len(found)} illumination function(s) (.npy), expected {expected} (one for each "
            "SaveImages "
            f"module of the illumination pipeline that saves .npy): {[os.path.basename(p) for p in found]}"
        )
    names = [os.path.basename(path) for path in found]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        errors.append(f"two functions have the same file name, so one would replace the other: {duplicates}")

    # A pipeline can calculate functions for some channels only (for example not for brightfield): only warn.
    if args.channels and expected and args.channels != expected:
        warnings.append(
            f"{expected} illumination function(s) for {args.channels} channel(s) per image set. "
            "Check that the analysis pipeline corrects the channels that you expect."
        )

    # Step 3: the values of each function.
    functions = {os.path.basename(path): check_function(path, errors) for path in found}

    # Step 4: copy the functions into one folder, and write the QC file. The workflow publishes both.
    os.makedirs(args.dest, exist_ok=True)
    if not errors:
        for path in found:
            shutil.copyfile(path, os.path.join(args.dest, os.path.basename(path)))
    qc = {"expected": expected, "functions": functions, "warnings": warnings, "errors": errors}
    with open(args.qc, "w", encoding="utf-8") as handle:
        json.dump(qc, handle, indent=2)

    for warning in warnings:
        print(f"[check_illum] WARNING: {warning}", file=sys.stderr)
    if errors:
        for error in errors:
            print(f"[check_illum] ERROR: {error}", file=sys.stderr)
        print("\n----- last 40 lines of the CellProfiler log -----", file=sys.stderr)
        print("\n".join(log_text.splitlines()[-40:]), file=sys.stderr)
        sys.exit(1)
    print(f"[check_illum] OK: {len(found)} illumination function(s): {sorted(functions)}")


if __name__ == "__main__":
    main()
