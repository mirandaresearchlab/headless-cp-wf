#!/usr/bin/env python3
"""Compare the published masks and per-cell tables of two runs. Match by acquisition, not batch.

Use it to prove that batching does not change results. Run the same image sets in one batch
and in several batches, with the same illumination files. Then compare the two runs.

    python tests/compare_runs.py projects/<run_a> projects/<run_b>

Checks:
  - Both runs have the same masks (plate, acquisition, object type). The pixel values are equal.
  - Both runs have the same cp_features/*.csv.gz files with the same columns.
  - Rows appear in the same order with the same keys.
  - Every value agrees. IDs, counts and parent/child links must be equal. Other numbers may
    differ by rtol=1e-6 (floating point rounding only).
Columns that depend on the batch (Metadata_Batch, ImageNumber, execution times, paths) are skipped.
"""
import argparse
import csv
import gzip
import json
from pathlib import Path

import numpy as np
import tifffile


# Batch-dependent bookkeeping. Everything else must agree.
SKIP = {'Metadata_Batch', 'Metadata_ImageNumber', 'Image_Group_Index', 'Image_Group_Number', 'Image_Group_Length'}
SKIP_PREFIXES = ('Image_ExecutionTime_', 'Image_PathName_', 'Image_URL_', 'Image_FileName_Illum', 'Image_PathName_Illum')

# IDs and keys must match exactly. Measurements may differ by floating point rounding only.
EXACT = ('Metadata_', 'Cells_ObjectNumber', 'Cytoplasm_ObjectNumber', 'Nuclei_ObjectNumber')


def masks(root):
    """List the masks of one run.

    Args:
        root: the run folder, e.g. projects/one.

    Returns:
        {(plate, mask filename): path}. Mask names do not depend on the batch, so two runs
        with different batch sizes give the same keys.
    """
    return {(path.parent.name, path.name): path for path in root.glob('masks/*/*.tiff')}


def same_value(column, a, b, where):
    """Check one value against the same value of the other run.

    Args:
        column: the column name.
        a: the value in the first run, as text.
        b: the value in the second run, as text.
        where: the table and row, for the error message.

    Returns:
        1 if the value was checked, 0 if the column is skipped.

    Raises:
        AssertionError: if the values differ.
    """
    if column in SKIP or column.startswith(SKIP_PREFIXES):
        return 0

    # Text values must be equal. Numbers are compared as numbers.
    try:
        x, y = float(a), float(b)
    except ValueError:
        assert a == b, (where, column, a, b)
        return 1
    if column.startswith(EXACT) or '_Count_' in column or '_Parent_' in column or '_Children_' in column:
        assert x == y or (np.isnan(x) and np.isnan(y)), (where, column, a, b)
    else:

        # Same algorithm and pixels: tight tolerance allows only floating point roundoff.
        np.testing.assert_allclose(x, y, rtol=1e-6, atol=1e-8, equal_nan=True, err_msg=str((where, column)))
    return 1


def compare(left, right):
    """Compare two run folders. Stop at the first difference.

    Args:
        left: the first run folder.
        right: the second run folder.

    Returns:
        A summary: number of masks, values and rows compared. It is also printed.
    """

    # The same masks with the same pixel values.
    masks_a, masks_b = masks(left), masks(right)
    assert masks_a and masks_a.keys() == masks_b.keys(), 'Mask acquisition/type mismatch'
    for key, path in masks_a.items():
        np.testing.assert_array_equal(tifffile.imread(path), tifffile.imread(masks_b[key]), err_msg=str(key))

    # The same feature tables, read side by side, row by row.
    files = sorted(p.name for p in (left / 'cp_features').glob('*.csv.gz'))
    assert files and files == sorted(p.name for p in (right / 'cp_features').glob('*.csv.gz')), 'Feature tables differ'
    checked, rows = 0, {}
    for name in files:
        with gzip.open(left / 'cp_features' / name, 'rt', newline='') as a, gzip.open(right / 'cp_features' / name, 'rt', newline='') as b:
            ra, rb = csv.reader(a), csv.reader(b)
            header = next(ra)
            assert header == next(rb), f'Columns differ: {name}'
            n = 0
            for n, (x, y) in enumerate(zip(ra, rb), 1):
                row, other = dict(zip(header, x)), dict(zip(header, y))

                # Rows must come in the same order: same plate, image and cell.
                key = lambda r: (r['Metadata_Plate'], r['Metadata_PlateImageNumber'], r['Metadata_Acquisition'], r['Metadata_ObjectNumber'])
                assert key(row) == key(other), f'Row order differs: {name} row {n}: {key(row)} vs {key(other)}'
                checked += sum(same_value(c, row[c], other[c], (name, n)) for c in header)
            assert next(ra, None) is None and next(rb, None) is None, f'Row counts differ: {name}'
            rows[name] = n
    result = dict(equal=True, masks=len(masks_a), values=checked, rows=rows)
    print(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('left', type=Path)
    parser.add_argument('right', type=Path)
    args = parser.parse_args()
    compare(args.left, args.right)
