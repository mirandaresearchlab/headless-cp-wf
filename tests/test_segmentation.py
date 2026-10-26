"""Unit tests for the SaveLabelMasks plugin.

They load the real cp-configs/2_analysis.cppipe with CellProfiler. They need the conda
environment with Java.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import tifffile
from cellprofiler_core.preferences import set_headless, set_default_output_directory


# CellProfiler must know there is no screen before it loads any modules.
set_headless()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))
sys.path.insert(0, str(ROOT / 'plugins'))

from prepare import load_pipeline


class FakeMeasurements:
    """Minimal stand-in for CellProfiler image measurements of one image set."""
    image_set_number = 1

    def __init__(self, values):
        """Store the image measurements as a dict of name to value."""
        self.values = values

    def get_current_image_measurement(self, name):
        """Return one image measurement."""
        return self.values[name]

    def has_feature(self, table, name):
        """Return True for image measurements that exist."""
        return table == 'Image' and name in self.values

    def get_feature_names(self, table):
        """Return all image measurement names."""
        return list(self.values)


def save_masks(tmp_path, labels):
    """Run SaveLabelMasks on two object types with the real analysis pipeline.

    Args:
        tmp_path: the pytest temporary folder. The masks are written to tmp_path/masks.
        labels: the label image to use for both object types.

    Returns:
        {object name: (labels, provenance)}, read back from the saved TIFFs.
    """
    import json
    from cellprofiler_core.object import Objects, ObjectSet
    from savelabelmasks import SaveLabelMasks

    # Two object types with the same labels: the first nuclei and the final, masked nuclei.
    object_set = ObjectSet()
    for name in ('NucleiPaired', 'Nuclei'):
        objects = Objects()
        objects.segmented = labels
        object_set.add_objects(objects, name)

    # Measurements as LoadData would set them: metadata, and a file name and folder per image.
    values = {'Metadata_Plate': 'P1', 'Metadata_Batch': 'batch_0001', 'Metadata_Acquisition': 'A01_s1_x0_y0',
              'Metadata_Well': 'A01'}
    for channel in ('DNA', 'RNA', 'AGP', 'Mito', 'ER'):
        values.update({f'FileName_{channel}': f'{channel}.tiff', f'PathName_{channel}': '/raw/P1',
                       f'FileName_Illum{channel}': f'Illum{channel}.npy', f'PathName_Illum{channel}': '/illum/P1'})

    # Number 100 puts the module after every module of the real pipeline.
    module = SaveLabelMasks()
    module.set_module_num(100)
    set_default_output_directory(str(tmp_path))
    module.run(SimpleNamespace(measurements=FakeMeasurements(values), object_set=object_set,
                               pipeline=load_pipeline(ROOT / 'cp-configs/2_analysis.cppipe')))

    # Read every mask back. The file name is <image name>_<object>.tiff.
    result = {}
    for path in (tmp_path / 'masks').glob('*.tiff'):
        with tifffile.TiffFile(path) as tiff:
            result[path.stem[len('A01_s1_x0_y0_'):]] = (tiff.asarray(), json.loads(tiff.pages[0].description))
    return result


def test_masks_preserve_large_labels(tmp_path):
    """Labels above 65535 are saved without loss as uint32."""
    labels = np.array([[0, 1, 1], [70000, 70000, 0]], dtype=np.uint32)
    saved, provenance = save_masks(tmp_path, labels)['Nuclei']
    assert saved.dtype == np.uint32
    np.testing.assert_array_equal(saved, labels)
    assert provenance['metadata']['Well'] == 'A01' and provenance['object'] == 'Nuclei'


def test_mask_provenance_traces_source_images(tmp_path):
    """The provenance lists only the files that each object depends on, through the correct pipeline steps."""
    masks = save_masks(tmp_path, np.array([[0, 1], [1, 0]], dtype=np.uint32))

    # Primary nuclei come only from the corrected DNA image, not from the other channels.
    _, primary = masks['NucleiPaired']
    assert primary['source_files'] == {'DNA': {'file': 'DNA.tiff', 'folder': '/raw/P1'},
                                       'IllumDNA': {'file': 'IllumDNA.npy', 'folder': '/illum/P1'}}
    assert [(s['output'], s['module'], s['inputs']) for s in primary['steps']] == [
        ('NucleiPaired', 'IdentifyPrimaryObjects', ['CorrDNA']),
        ('CorrDNA', 'CorrectIlluminationApply', ['DNA', 'IllumDNA'])]

    # Final nuclei are masked by cells, which were grown on the AGP+ER cell body image.
    _, final = masks['Nuclei']
    assert sorted(final['source_files']) == ['AGP', 'DNA', 'ER', 'IllumAGP', 'IllumDNA', 'IllumER']
    assert [s['output'] for s in final['steps']][:2] == ['Nuclei', 'NucleiPaired']
