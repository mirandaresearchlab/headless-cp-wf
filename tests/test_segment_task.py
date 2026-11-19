"""Unit tests for the SEGMENT task and the mask hand-over to ANALYSIS (bin/run_task.py).

SEGMENT runs several CellProfiler workers on one group of batches. These tests check the parts
that decide correctness and order: how the image sets are cut between the workers, and how the
masks of all workers are checked and sorted into one folder per batch. They need only NumPy,
tifffile and pytest.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest
import tifffile

# The scripts in bin/ are not a package. Add the folder to the import path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from cp_inputs import read_csv, write_csv
from run_task import check_segmentation, collect_masks, compare_masks, split


@pytest.mark.parametrize('rows', [1, 2, 7, 9, 72])
@pytest.mark.parametrize('workers', [1, 3, 4, 16])
def test_split_keeps_every_row_once_in_order(rows, workers):
    """Joining the parts gives the rows back unchanged. Parts differ in size by at most one."""
    parts = split(list(range(rows)), workers)
    assert [r for part in parts for r in part] == list(range(rows))
    assert len(parts) == min(rows, workers) and all(parts)
    assert max(map(len, parts)) - min(map(len, parts)) <= 1


def manifest_row(batch, acquisition):
    """One manifest row, as SEGMENT has it after the illumination files were added."""
    return dict(Metadata_Plate='P1', Metadata_Batch=batch, Metadata_Acquisition=acquisition,
                FileName_DNA=f'{acquisition}_dna.tiff', PathName_DNA='/raw/P1',
                FileName_IllumDNA='IllumDNA.npy', PathName_IllumDNA='/illum/P1')


# Three image sets in two batches. Worker 1 gets the first two, worker 2 the last one.
ROWS = [manifest_row('batch_0001', 'A01_s1'), manifest_row('batch_0001', 'A01_s2'), manifest_row('batch_0002', 'A02_s1')]


def worker_output(folder, rows, obj='Nuclei', change=None):
    """Write what SaveLabelMasks writes in one worker: masks/<acquisition>_<object>.tiff and mask_manifest.csv.

    Each image set gets a different label image (its position + 1 objects), so a mask that
    lands in the wrong batch or image set is visible.

    Args:
        folder: the worker output folder.
        rows: the manifest rows of this worker.
        obj: the object name.
        change: a function that gets (row, provenance) and may change the provenance.
    """
    (folder / 'masks').mkdir(parents=True)
    entries = []
    for number, row in enumerate(rows, 1):
        labels = np.zeros((4, 4), np.uint32)
        count = ROWS.index(row) + 1
        labels.flat[:count] = np.arange(1, count + 1)
        provenance = dict(object=obj, metadata={k[len('Metadata_'):]: v for k, v in row.items() if k.startswith('Metadata_')},
                          source_files={n: dict(file=row['FileName_' + n], folder=row['PathName_' + n]) for n in ('DNA', 'IllumDNA')})
        if change:
            change(row, provenance)
        name = f'{row["Metadata_Acquisition"]}_{obj}.tiff'
        tifffile.imwrite(folder / 'masks' / name, labels, description=json.dumps(provenance), metadata=None)
        entries.append(dict(Plate='P1', Batch=row['Metadata_Batch'], Acquisition=row['Metadata_Acquisition'],
                            ImageNumber=str(number), ObjectType=obj, MaskPath='masks/' + name, LabelCount=str(count)))
    write_csv(folder / 'mask_manifest.csv', entries, list(entries[0]))


def test_masks_go_to_their_own_batch(tmp_path):
    """Each mask goes to the folder of its batch, unchanged, with a manifest and validation.json."""
    worker_output(tmp_path / 'w1', ROWS[:2])
    worker_output(tmp_path / 'w2', ROWS[2:])
    summary = collect_masks([tmp_path / 'w1', tmp_path / 'w2'], ROWS, ['Nuclei'], tmp_path / 'out', 'P1', 'segment_0001')

    assert sorted(p.name for p in (tmp_path / 'out').iterdir()) == ['batch_0001', 'batch_0002']
    first = read_csv(tmp_path / 'out/batch_0001/mask_manifest.csv')
    assert [(r['Acquisition'], r['LabelCount']) for r in first] == [('A01_s1', '1'), ('A01_s2', '2')]
    labels = tifffile.imread(tmp_path / 'out/batch_0002/masks/A02_s1_Nuclei.tiff')
    assert labels.max() == 3 and labels.dtype == np.uint32
    validation = json.loads((tmp_path / 'out/batch_0002/validation.json').read_text())
    assert (validation['plate'], validation['batch'], validation['segment'], validation['image_sets']) == ('P1', 'batch_0002', 'segment_0001', 1)
    assert summary['masks'] == 3


def test_missing_mask_stops_segment(tmp_path):
    """A worker that did not save the mask of one image set stops the task."""
    worker_output(tmp_path / 'w1', ROWS[:2])
    with pytest.raises(ValueError, match='missing'):
        collect_masks([tmp_path / 'w1'], ROWS, ['Nuclei'], tmp_path / 'out', 'P1', 'segment_0001')


def test_mask_saved_twice_stops_segment(tmp_path):
    """Two workers that saved the same image set stop the task (overlapping parts)."""
    worker_output(tmp_path / 'w1', ROWS[:2])
    worker_output(tmp_path / 'w2', ROWS[1:])
    with pytest.raises(ValueError, match='duplicate'):
        collect_masks([tmp_path / 'w1', tmp_path / 'w2'], ROWS, ['Nuclei'], tmp_path / 'out', 'P1', 'segment_0001')


@pytest.mark.parametrize('change', [
    lambda row, p: p['metadata'].update(Acquisition='A09_s9'),
    lambda row, p: p['source_files']['DNA'].update(file='other.tiff'),
    lambda row, p: p['source_files']['IllumDNA'].update(folder='/illum/P2'),
    lambda row, p: p.update(object='Cells'),
])
def test_mask_of_other_files_stops_segment(tmp_path, change):
    """A mask must name its image set and exactly the raw images and illumination files of that image set."""
    worker_output(tmp_path / 'w1', ROWS, change=lambda row, p: change(row, p) if row is ROWS[1] else None)
    with pytest.raises(ValueError, match='provenance'):
        collect_masks([tmp_path / 'w1'], ROWS, ['Nuclei'], tmp_path / 'out', 'P1', 'segment_0001')


def segmented_batch(tmp_path):
    """Collect the masks of the two batches. Return the folder of batch_0001."""
    worker_output(tmp_path / 'w1', ROWS)
    collect_masks([tmp_path / 'w1'], ROWS, ['Nuclei'], tmp_path / 'out', 'P1', 'segment_0001')
    return tmp_path / 'out/batch_0001'


def test_analysis_accepts_only_the_masks_of_its_batch(tmp_path):
    """ANALYSIS checks that the segmentation folder is for its plate, batch and image sets."""
    folder = segmented_batch(tmp_path)
    check_segmentation(folder, 'P1', 'batch_0001', ROWS[:2], ['Nuclei'])
    with pytest.raises(ValueError, match='batch_0002'):
        check_segmentation(folder, 'P1', 'batch_0002', ROWS[:2], ['Nuclei'])
    with pytest.raises(ValueError, match='image sets'):
        check_segmentation(folder, 'P1', 'batch_0001', ROWS[:1], ['Nuclei'])


def test_analysis_masks_must_equal_segmentation_masks(tmp_path):
    """The masks that ANALYSIS saves for the Cellpose objects must be the SEGMENT masks, label for label."""
    folder = segmented_batch(tmp_path)
    analysis = tmp_path / 'analysis'
    (analysis / 'masks').mkdir(parents=True)
    entries = read_csv(folder / 'mask_manifest.csv')
    for entry in entries:
        (analysis / entry['MaskPath']).write_bytes((folder / entry['MaskPath']).read_bytes())
    write_csv(analysis / 'mask_manifest.csv', entries, list(entries[0]))
    assert compare_masks(analysis, folder, ['Nuclei']) == 2

    # Swap two labels in one mask: same objects, other numbers. That is not the same mask.
    path = analysis / entries[1]['MaskPath']
    labels = tifffile.imread(path)
    tifffile.imwrite(path, np.choose(labels, [0, 2, 1]).astype(np.uint32))
    with pytest.raises(ValueError, match='differs'):
        compare_masks(analysis, folder, ['Nuclei'])
