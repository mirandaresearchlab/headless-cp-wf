"""Unit tests for input checks (bin/cp_inputs.py).

They use the real cp-configs pipelines and small synthetic TIFFs. Each test proves that one kind
of bad input stops the run with a clear message.
"""
import sys
from pathlib import Path

import numpy as np
import pytest
import tifffile


# The scripts in bin/ are not a package. Add the folder to the import path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))


def settings():
    """Read the naming rules from the real cp-configs pipelines."""
    from cp_inputs import read_config
    return read_config(Path(__file__).resolve().parents[1] / 'cp-configs')


def make_images(tmp_path, channels=('405', '488', '561', '638', '730')):
    """Write one small TIFF per channel for well A02, site 1 in plate P1.

    Args:
        tmp_path: the pytest temporary folder.
        channels: the wavelengths to write. The default is the five real channels.

    Returns:
        The paths of the written files.
    """
    plate = tmp_path / 'P1'
    plate.mkdir()
    paths = []
    for channel in channels:

        # Same filename pattern as the real images, e.g. A02_s1_x0_y0_Fluorescence_405_nm_Ex.tiff.
        path = plate / f'A02_s1_x0_y0_Fluorescence_{channel}_nm_Ex.tiff'
        tifffile.imwrite(path, np.zeros((16, 16), dtype=np.uint16))
        paths.append(path)
    return paths


def test_configuration_uses_real_mapping():
    """The channel numbers in the filenames map to the CellProfiler image names of the pipelines."""
    config = settings()
    assert config['channels'] == {'405': 'DNA', '488': 'RNA', '561': 'AGP', '638': 'Mito', '730': 'ER'}


def test_complete_set_and_metadata(tmp_path):
    """Five channel files form one image set. The plate comes from the folder. No FOV field is invented."""
    from cp_inputs import validate_images
    rows = validate_images(make_images(tmp_path), settings())

    # Five files, one image set. Row and Column come from the Well group of the regex.
    assert len(rows) == 1
    assert rows[0]['metadata'] == dict(Plate='P1', Well='A02', Row='A', Column='02', Site='1', X='0', Y='0')
    assert 'FOV' not in rows[0]['metadata']
    assert rows[0]['name'] == 'A02_s1_x0_y0'


def test_missing_channel(tmp_path):
    """An image set without one channel stops the run and names that channel."""
    from cp_inputs import validate_images

    # Leave out the last channel (730 nm).
    with pytest.raises(ValueError, match='missing.*730'):
        validate_images(make_images(tmp_path)[:-1], settings())


def test_duplicate_channel(tmp_path):
    """Two files for the same channel of one image set stop the run."""
    from cp_inputs import validate_images
    paths = make_images(tmp_path)

    # Give the 405 nm file twice.
    with pytest.raises(ValueError, match='duplicate.*405'):
        validate_images(paths + paths[:1], settings())


def test_unknown_channel_is_not_accepted_by_count(tmp_path):
    """Five files are not enough. An unknown channel stops the run even though the count is right."""
    from cp_inputs import validate_images
    with pytest.raises(ValueError, match='unknown.*999'):
        validate_images(make_images(tmp_path, ('405', '488', '561', '638', '999')), settings())


def test_multiplane_rejected(tmp_path):
    """A TIFF with more than one plane stops the run."""
    from cp_inputs import validate_images
    paths = make_images(tmp_path)

    # Replace one file with a stack of two planes.
    tifffile.imwrite(paths[0], np.zeros((2, 16, 16), dtype=np.uint16), photometric='minisblack')
    with pytest.raises(ValueError, match='single-plane'):
        validate_images(paths, settings())


def test_cp_matching_ambiguity_rejected(tmp_path):
    """Two files that CellProfiler would put in the same image set stop the run."""
    from cp_inputs import validate_images
    paths = make_images(tmp_path)

    # A second set that differs only in X. CellProfiler matches on Well and Site, so it would mix them.
    for path in paths[:]:
        other = path.with_name(path.name.replace('_x0_', '_x1_'))
        tifffile.imwrite(other, np.zeros((16, 16), dtype=np.uint16))
        paths.append(other)
    with pytest.raises(ValueError, match='ambiguous.*Well.*Site'):
        validate_images(paths, settings())


def test_configuration_rejects_missing_and_extra_pipelines(tmp_path):
    """The config folder must hold exactly the two expected .cppipe files."""
    import shutil
    from cp_inputs import read_config
    source = Path(__file__).resolve().parents[1] / 'cp-configs'

    # Only one pipeline: too few.
    shutil.copy(source / '1_illumination.cppipe', tmp_path)
    with pytest.raises(ValueError, match='exactly'):
        read_config(tmp_path)

    # Both pipelines plus an extra one: too many.
    shutil.copy(source / '2_analysis.cppipe', tmp_path)
    shutil.copy(source / '2_analysis.cppipe', tmp_path / 'extra.cppipe')
    with pytest.raises(ValueError, match='exactly'):
        read_config(tmp_path)
