"""Unit tests for the per-batch output checks and the CellProfiler 4.2.8.1 realignment (bin/run_task.py).

The tests write small fake CellProfiler outputs (CSVs, uint32 masks, mask_manifest.csv).
"""
import sys
from pathlib import Path

import numpy as np
import pytest
import tifffile


# The scripts in bin/ are not a package. Add the folder to the import path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from prepare import write_csv
from run_task import realign, validate_analysis


def mask(path, labels, obj):
    """Write a uint32 mask with the same provenance JSON that SaveLabelMasks writes.

    Args:
        path: the TIFF file to write.
        labels: the label image. 0 is background, any other value is an object number.
        obj: the object type, e.g. "Cells".
    """
    import json
    provenance = dict(object=obj, metadata=dict(Plate='P1', Batch='batch_0001', Acquisition='Site-1'),
                      source_files={'DNA': dict(file='dna.tiff', folder='/raw')})
    tifffile.imwrite(path, labels.astype(np.uint32), description=json.dumps(provenance), metadata=None)


def outputs(folder, count='2.0'):
    """Write the outputs of one image set with two cells, as CellProfiler would.

    Args:
        folder: the fake batch folder.
        count: the value of Count_Cells in Image.csv.

    Returns:
        The manifest rows of the batch, including the loaded file names.
    """
    row = dict(Metadata_Plate='P1', Metadata_Batch='batch_0001', Metadata_Acquisition='Site-1')
    loaded = dict(row, FileName_DNA='dna.tiff', PathName_DNA='/raw')

    # Image.csv with the count, Cells.csv with cells 1 and 2, and a mask where both have pixels.
    write_csv(folder / 'features/Image.csv', [dict(row, ImageNumber='1', Count_Cells=count)])
    write_csv(folder / 'features/Cells.csv', [dict(row, ImageNumber='1', ObjectNumber=str(n)) for n in (1, 2)])
    (folder / 'masks').mkdir()
    mask(folder / 'masks/Cells.tiff', np.array([[0, 1], [2, 2]]), 'Cells')
    write_csv(folder / 'mask_manifest.csv', [dict(Plate='P1', Batch='batch_0001', Acquisition='Site-1',
              ImageNumber='1', ObjectType='Cells', MaskPath='masks/Cells.tiff', LabelCount='2')])
    return [loaded]


def test_cp_floating_count_export(tmp_path):
    """Counts written as "2.0" are accepted."""

    # CP 4.2.8.1 exports integral counts as strings such as '450.0'.
    rows = outputs(tmp_path)
    assert validate_analysis(tmp_path, rows, {'objects': ['Cells']})['masks'] == 1


def test_fractional_counts_are_invalid(tmp_path):
    """A count that is not a whole number fails."""
    rows = outputs(tmp_path, '2.5')
    with pytest.raises(ValueError):
        validate_analysis(tmp_path, rows, {'objects': ['Cells']})


def test_unexpected_mask_labels_are_invalid(tmp_path):
    """A mask label without a measurement row fails."""
    rows = outputs(tmp_path)

    # Label 3 is in the mask, but Cells.csv has only rows 1 and 2.
    mask(tmp_path / 'masks/Cells.tiff', np.array([[0, 1], [2, 3]]), 'Cells')
    with pytest.raises(ValueError, match='disagree'):
        validate_analysis(tmp_path, rows, {'objects': ['Cells']})


def shifted_outputs(folder):
    """Write four cytoplasms where number 2 has no pixels.

    The values are shifted the same way CellProfiler 4.2.8.1 writes them. The values of
    objects 3 and 4 sit on rows 2 and 3. The last row is empty.

    Args:
        folder: the fake batch folder.

    Returns:
        The manifest rows of the batch.
    """
    row = dict(Metadata_Plate='P1', Metadata_Batch='batch_0001', Metadata_Acquisition='Site-1')
    loaded = dict(row, FileName_DNA='dna.tiff', PathName_DNA='/raw')

    # Objects 1, 3 and 4 have pixels. Object 2 has none.
    labels = np.array([[1, 1, 3, 4], [1, 3, 3, 4]], dtype=np.uint32)
    area = {1: 3, 3: 3, 4: 2}
    center = {n: float(np.mean(np.nonzero(labels == n)[1])) for n in area}
    write_csv(folder / 'features/Image.csv', [dict(row, ImageNumber='1', Count_Cytoplasm='4.0')])

    # Shifted columns: the values of objects 1, 3, 4 on rows 1, 2, 3. Zernike is aligned already.
    shifted = [area[1], area[3], area[4], 'nan']
    centers = [center[1], center[3], center[4], 'nan']
    write_csv(folder / 'features/Cytoplasm.csv', [dict(
        row, ImageNumber='1', ObjectNumber=str(n), AreaShape_Area=str(shifted[n - 1]),
        AreaShape_Center_X=str(centers[n - 1]), AreaShape_MeanRadius=['1.5', '1.25', '1.0', '0.0'][n - 1],
        Texture_Contrast_DNA_3_00_256=['0.1', '0.3', '0.4', 'nan'][n - 1],
        AreaShape_Zernike_0_0=['0.9', '0.0', '0.7', '0.6'][n - 1],
        Location_Center_X=str(center.get(n, 'nan'))) for n in (1, 2, 3, 4)])
    (folder / 'masks').mkdir()
    mask(folder / 'masks/Cytoplasm.tiff', labels, 'Cytoplasm')
    write_csv(folder / 'mask_manifest.csv', [dict(Plate='P1', Batch='batch_0001', Acquisition='Site-1',
              ImageNumber='1', ObjectType='Cytoplasm', MaskPath='masks/Cytoplasm.tiff', LabelCount='3')])
    return [loaded]


def test_shifted_measurements_fail_validation(tmp_path):
    """Without realignment, shifted values fail the area check."""
    rows = shifted_outputs(tmp_path)
    with pytest.raises(ValueError, match='AreaShape_Area does not match'):
        validate_analysis(tmp_path, rows, {'objects': ['Cytoplasm']})


def test_realign_restores_object_rows(tmp_path):
    """Realignment moves shifted values to their objects and leaves aligned columns unchanged."""
    import csv
    rows = shifted_outputs(tmp_path)
    corrections = realign(tmp_path, {'objects': ['Cytoplasm']})

    # Object 2 is the empty one. Its values become nan, and the others move back to their rows.
    assert [(c['object'], c['empty_objects']) for c in corrections] == [('Cytoplasm', [2])]
    table = list(csv.DictReader((tmp_path / 'features/Cytoplasm.csv').open()))
    assert [r['AreaShape_Area'] for r in table] == ['3', 'nan', '3', '2']
    assert [r['AreaShape_MeanRadius'] for r in table] == ['1.5', 'nan', '1.25', '1.0']
    assert [r['Texture_Contrast_DNA_3_00_256'] for r in table] == ['0.1', 'nan', '0.3', '0.4']

    # Object-indexed modules were already aligned and stay unchanged.
    assert [r['AreaShape_Zernike_0_0'] for r in table] == ['0.9', '0.0', '0.7', '0.6']
    assert validate_analysis(tmp_path, rows, {'objects': ['Cytoplasm']})['empty_objects'] == {'Cytoplasm': 1}


def test_realign_rejects_unknown_layout(tmp_path):
    """Realignment stops if the values do not show the known shift pattern."""
    shifted_outputs(tmp_path)
    path = tmp_path / 'features/Cytoplasm.csv'

    # Put a value into the last row. The known shift always leaves that row empty.
    lines = path.read_text().splitlines()
    path.write_text('\n'.join(lines[:-1] + [lines[-1].replace(',nan,', ',5,', 1)]) + '\n')
    with pytest.raises(ValueError, match='known CP 4.2.8.1 shift'):
        realign(tmp_path, {'objects': ['Cytoplasm']})


def test_mask_provenance_must_match_image_set(tmp_path):
    """A mask that names a different source file fails."""
    rows = outputs(tmp_path)

    # The batch loaded the DNA image from another folder than the one the mask names.
    rows[0]['PathName_DNA'] = '/elsewhere'
    with pytest.raises(ValueError, match='provenance'):
        validate_analysis(tmp_path, rows, {'objects': ['Cells']})
