"""Tests for the adaptive threshold window check in PREPARE (issue #11).

CellProfiler stops in ANALYSIS if an adaptive threshold window is more than half of an image side.
PREPARE must find this before any task runs. The tests check the rule against CellProfiler itself,
read the windows of the real pipelines, and run PREPARE on small and large synthetic images.

They load real pipelines with CellProfiler, so they need the conda environment with Java.
"""

import csv
import sys
from pathlib import Path

import numpy as np
import pytest
import tifffile
from cellprofiler_core.preferences import set_headless, set_plugin_directory

# CellProfiler must know there is no screen, and where the plugins are, before it loads modules.
set_headless()
ROOT = Path(__file__).resolve().parents[1]
set_plugin_directory(str(ROOT / 'plugins'))
sys.path.insert(0, str(ROOT / 'bin'))
sys.path.insert(0, str(ROOT / 'plugins'))

from prepare import adaptive_windows, check_adaptive_windows, load_pipeline, prepare  # noqa: E402

CONFIGS = ROOT / 'cp-configs'
CHANNELS = ('DNA', 'RNA', 'AGP', 'Mito', 'ER')


def analysis_modules():
    """The modules of the example analysis pipeline."""
    return load_pipeline(CONFIGS / '2_analysis.cppipe').modules()


def secondary(modules):
    """The IdentifySecondaryObjects module, the one with an adaptive window in the example."""
    return next(m for m in modules if m.module_name == 'IdentifySecondaryObjects')


def samplesheet(tmp_path, shape):
    """Write one image set of zeros (five channels, plate P1) and its samplesheet. Return the sheet."""
    rows = []
    for channel in CHANNELS:
        path = tmp_path / 'P1' / f'A02_1_{channel}.tif'
        path.parent.mkdir(exist_ok=True)
        tifffile.imwrite(path, np.zeros(shape, dtype=np.uint16))
        rows.append(dict(plate='P1', well='A02', site='1', channel=channel, path=str(path)))
    sheet = tmp_path / 'samplesheet.csv'
    with sheet.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return sheet


@pytest.mark.parametrize('shape', [(1001, 1024), (1024, 1001), (1002, 1002), (1024, 1024)])
def test_rule_matches_cellprofiler(shape):
    """Known answer from CellProfiler: a 501-pixel window fails at 1001 pixels and works at 1002.
    The PREPARE check must fail exactly when CellProfiler fails."""
    threshold = secondary(analysis_modules()).threshold
    assert threshold.adaptive_window_size.value == 501
    image = np.random.default_rng(0).random(shape)
    try:
        threshold.get_local_threshold(image, np.ones(shape, dtype=bool), False)
        cellprofiler_fails = False
    except ValueError as error:
        assert 'Adaptive window cannot exceed 50%' in str(error)
        cellprofiler_fails = True
    try:
        check_adaptive_windows([('IdentifySecondaryObjects #9', 501)], {'P1': shape})
        prepare_fails = False
    except ValueError:
        prepare_fails = True
    assert prepare_fails == cellprofiler_fails == (min(shape) < 1002)


def test_example_pipelines_have_one_adaptive_window():
    """The example: nuclei use a global threshold, cells an adaptive window of 501 pixels."""
    assert adaptive_windows(analysis_modules()) == [('IdentifySecondaryObjects #9', 501)]
    assert adaptive_windows(load_pipeline(CONFIGS / '1_illumination.cppipe').modules()) == []


@pytest.mark.parametrize(
    'change',
    [
        lambda m: setattr(m.threshold.threshold_scope, 'value', 'Global'),
        lambda m: setattr(m.threshold.local_operation, 'value', 'Sauvola'),
        lambda m: setattr(m.method, 'value', 'Distance - N'),
        lambda m: setattr(m, 'enabled', False),
    ],
    ids=['global', 'sauvola', 'distance-n', 'disabled'],
)
def test_unused_window_is_not_checked(change):
    """CellProfiler does not use the window in these cases, so they must not stop a run."""
    modules = analysis_modules()
    change(secondary(modules))
    assert adaptive_windows(modules) == []


def test_prepare_stops_on_images_smaller_than_twice_the_window(tmp_path):
    """The tutorial bug: 512 x 512 crops with a 501-pixel window. PREPARE stops with the sizes."""
    sheet = samplesheet(tmp_path, (512, 512))
    with pytest.raises(ValueError, match=r'IdentifySecondaryObjects #9 .* 501 pixels.* P1 are 512 x 512 pixels.*\(256 pixels\)'):
        prepare(CONFIGS, sheet, [], 4, tmp_path / 'prepared')


def test_prepare_accepts_tutorial_size_and_records_the_windows(tmp_path):
    """The 1024 x 1024 tutorial crops pass, and the contract records the window."""
    import json

    sheet = samplesheet(tmp_path, (1024, 1024))
    prepare(CONFIGS, sheet, [], 4, tmp_path / 'prepared')
    contract = json.loads((tmp_path / 'prepared' / 'pipelines' / 'contract.json').read_text())
    assert contract['adaptive_windows'] == {'IdentifySecondaryObjects #9': 501}
