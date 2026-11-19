"""Tests for Cellpose-SAM support: the pipeline split in PREPARE and the LoadLabelMasks plugin.

They load real pipelines with CellProfiler, so they need the conda environment with Java.
The last test also runs Cellpose-SAM on the CPU. It needs the cpsam model file and is skipped
without it (set CELLPOSE_LOCAL_MODELS_PATH to the folder of the file).
"""

import json
import os
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest
import tifffile
from cellprofiler_core.preferences import set_default_image_directory, set_headless, set_plugin_directory

# CellProfiler must know there is no screen, and where the plugins are, before it loads modules.
set_headless()
ROOT = Path(__file__).resolve().parents[1]
set_plugin_directory(str(ROOT / 'plugins'))
sys.path.insert(0, str(ROOT / 'bin'))
sys.path.insert(0, str(ROOT / 'plugins'))

from prepare import adapt, load_pipeline  # noqa: E402

EXAMPLE = ROOT / 'cp-configs-cellpose'


def configs(tmp_path, change=None):
    """Copy the Cellpose example configuration, optionally change RunCellpose, and return the folder.

    Args:
        tmp_path: the pytest temporary folder.
        change: a function that gets the RunCellpose module and changes its settings.

    Returns:
        The folder with 1_illumination.cppipe and 2_analysis.cppipe.
    """
    folder = tmp_path / 'configs'
    folder.mkdir()
    shutil.copy(EXAMPLE / '1_illumination.cppipe', folder)
    analysis = load_pipeline(EXAMPLE / '2_analysis.cppipe')
    if change:
        change(next(m for m in analysis.modules() if m.module_name == 'RunCellpose'))
    with (folder / '2_analysis.cppipe').open('w') as stream:
        analysis.dump(stream)
    return folder


def prepared(tmp_path, change=None):
    """Run the pipeline part of PREPARE on the example. Return the contract and the output folder."""
    out = tmp_path / 'pipelines'
    out.mkdir()
    return adapt(configs(tmp_path, change), out), out


def module_names(path):
    """Return the module names of a .cppipe file, in order."""
    return [m.module_name for m in load_pipeline(path).modules()]


def test_cellpose_runs_in_its_own_pipeline(tmp_path):
    """SEGMENT gets RunCellpose and only the modules that make its input image, then saves the masks."""
    contract, out = prepared(tmp_path)
    assert module_names(out / 'segmentation.cppipe') == ['LoadData', 'CorrectIlluminationApply', 'RunCellpose', 'SaveLabelMasks']
    assert contract['segmentation'] == ['NucleiPaired']

    # The working copy runs Cellpose in this Python environment and keeps the model loaded.
    # SEGMENT chooses the device at run time, so the copy itself says CPU.
    cellpose = load_pipeline(out / 'segmentation.cppipe').modules()[2]
    assert (cellpose.docker_or_python.value, cellpose.cache_model.value, cellpose.use_gpu.value) == ('Python', True, False)


def test_analysis_loads_the_masks_in_place_of_cellpose(tmp_path):
    """ANALYSIS has every module of the source pipeline, with LoadLabelMasks in the place of RunCellpose."""
    contract, out = prepared(tmp_path)
    source = module_names(EXAMPLE / '2_analysis.cppipe')[4:]
    analysis = load_pipeline(out / 'analysis.cppipe').modules()
    names = [m.module_name for m in analysis]

    # LoadData first, SaveLabelMasks before the export, and the loader where RunCellpose was.
    expected = ['LoadData'] + [{'RunCellpose': 'LoadLabelMasks'}.get(n, n) for n in source]
    expected.insert(expected.index('ExportToSpreadsheet'), 'SaveLabelMasks')
    assert names == expected

    loader = analysis[names.index('LoadLabelMasks')]
    assert (loader.x_name.value, loader.y_name.value, loader.nuclei_image.value) == ('CorrDNA', 'NucleiPaired', 'None')
    assert 'NucleiPaired' in contract['objects']


def test_pipeline_without_cellpose_has_no_segmentation_step(tmp_path):
    """The classic pipeline does not get a SEGMENT pipeline, and its analysis copy has no loader."""
    out = tmp_path / 'pipelines'
    out.mkdir()
    contract = adapt(ROOT / 'cp-configs', out)
    assert contract['segmentation'] == [] and not (out / 'segmentation.cppipe').exists()
    assert 'LoadLabelMasks' not in module_names(out / 'analysis.cppipe')


@pytest.mark.parametrize(
    'change, message',
    [
        (lambda m: setattr(m.cellpose_version, 'value', 'v3'), 'Cellpose-SAM'),
        (lambda m: setattr(m.do_3D, 'value', True), '3D'),
        (lambda m: setattr(m.save_probabilities, 'value', True), 'probability'),
        (lambda m: (setattr(m.mode_v4, 'value', 'custom'), setattr(m.model_directory, 'value', 'Default Input Folder|')), 'absolute'),
    ],
)
def test_unsupported_cellpose_settings_stop_prepare(tmp_path, change, message):
    """Settings that SEGMENT cannot run, or cannot pass to ANALYSIS, stop the run before any task."""
    with pytest.raises(ValueError, match=message):
        prepared(tmp_path, change)


def test_custom_model_must_exist(tmp_path):
    """A custom model is read from an absolute folder. A missing file stops PREPARE."""

    def custom(module):
        module.mode_v4.value = 'custom'
        module.model_directory.value = f'Elsewhere...|{tmp_path}'
        module.model_file_name.value = 'missing_model'

    with pytest.raises(ValueError, match='missing_model'):
        prepared(tmp_path, custom)


def test_segment_task_does_not_change_the_prepare_pipeline(tmp_path, monkeypatch):
    """SEGMENT writes its GPU copy beside the input, never through the staged link into PREPARE's folder.

    Regression: Nextflow stages pipelines/segmentation.cppipe as a link with the same name. Writing
    the task copy to that name changed the PREPARE file, and SEGMENT tasks that started at the same
    time read a half-written file ("Invalid format for setting").
    """
    from run_task import run_segmentation
    import argparse

    _, out = prepared(tmp_path)
    source = out / 'segmentation.cppipe'
    before = source.read_bytes()
    task = tmp_path / 'task'
    task.mkdir()
    (task / 'segmentation.cppipe').symlink_to(source)
    monkeypatch.chdir(task)

    # Stop right after the pipeline copy: no workers and no Cellpose model are needed for this check.
    import run_task

    monkeypatch.setattr(run_task, 'split', lambda rows, workers: (_ for _ in ()).throw(RuntimeError('stop')))
    args = argparse.Namespace(
        pipeline=Path('segmentation.cppipe'),
        device='cpu',
        workers=2,
        cpus=2,
        plugins=ROOT / 'plugins',
        plate='P1',
        batch='segment_0001',
        kind='segmentation',
    )
    monkeypatch.setattr('cellpose.models.cache_CPSAM_model_path', lambda: None)
    with pytest.raises(RuntimeError, match='stop'):
        run_segmentation(args, [], task)
    assert source.read_bytes() == before


def test_nuclei_need_a_parent_cell_measurement(tmp_path):
    """MERGE joins nuclei to cells by Parent_Cells. Without RelateObjects, PREPARE stops."""
    folder = configs(tmp_path)
    analysis = load_pipeline(folder / '2_analysis.cppipe')
    analysis.remove_module(next(m for m in analysis.modules() if m.module_name == 'RelateObjects').module_num)
    with (folder / '2_analysis.cppipe').open('w') as stream:
        analysis.dump(stream)
    out = tmp_path / 'pipelines'
    out.mkdir()
    with pytest.raises(ValueError, match='Parent_Cells'):
        adapt(folder, out)


# ---------------------------------------------------------------------------------------------
# LoadLabelMasks
# ---------------------------------------------------------------------------------------------


def workspace(folder, metadata, files, image, pipeline=None):
    """Make a real CellProfiler workspace for one image set.

    Args:
        folder: the Default Input Folder.
        metadata: Plate, Batch and Acquisition of the image set.
        files: image name -> (file name, folder), as LoadData records them.
        image: the pixels of the image CorrDNA.
        pipeline: the pipeline of the workspace. Default: an empty pipeline.

    Returns:
        The workspace.
    """
    from cellprofiler_core.image import Image, ImageSetList
    from cellprofiler_core.measurement import Measurements
    from cellprofiler_core.object import ObjectSet
    from cellprofiler_core.pipeline import Pipeline
    from cellprofiler_core.workspace import Workspace

    set_default_image_directory(str(folder))
    measurements = Measurements()
    for key, value in metadata.items():
        measurements.add_image_measurement('Metadata_' + key, value)
    for name, (file, path) in files.items():
        measurements.add_image_measurement('FileName_' + name, file)
        measurements.add_image_measurement('PathName_' + name, path)
    image_set = ImageSetList().get_image_set(0)
    image_set.add('CorrDNA', Image(image))
    return Workspace(pipeline or Pipeline(), None, image_set, ObjectSet(), measurements, None)


METADATA = dict(Plate='P1', Batch='batch_0001', Acquisition='A01_s1')
FILES = {'DNA': ('dna.tiff', '/raw/P1'), 'IllumDNA': ('IllumDNA.npy', '/illum/P1')}


def segmentation_mask(folder, labels, metadata=METADATA, files=FILES, obj='NucleiPaired'):
    """Write a mask as SaveLabelMasks does in SEGMENT: <folder>/segmentation/masks/<acquisition>_<object>.tiff."""
    path = folder / 'segmentation' / 'masks' / f'{METADATA["Acquisition"]}_{obj}.tiff'
    path.parent.mkdir(parents=True, exist_ok=True)
    provenance = dict(object=obj, metadata=metadata, source_files={k: dict(file=f, folder=d) for k, (f, d) in files.items()})
    tifffile.imwrite(path, labels.astype(np.uint32), description=json.dumps(provenance), metadata=None)


def loader():
    """Make a LoadLabelMasks module for NucleiPaired on CorrDNA."""
    from loadlabelmasks import LoadLabelMasks

    module = LoadLabelMasks()
    module.x_name.value, module.y_name.value = 'CorrDNA', 'NucleiPaired'
    module.set_module_num(1)
    return module


def test_loader_adds_the_objects_and_measurements_of_the_mask(tmp_path):
    """The objects are the mask, and the measurements are those that RunCellpose records."""
    labels = np.zeros((6, 8), np.uint32)
    labels[1:3, 1:3] = 1
    labels[3:6, 4:8] = 2
    segmentation_mask(tmp_path, labels)
    work = workspace(tmp_path, METADATA, FILES, np.zeros((6, 8)))
    loader().run(work)

    np.testing.assert_array_equal(work.object_set.get_objects('NucleiPaired').segmented, labels)
    m = work.measurements
    assert m.get_current_image_measurement('Count_NucleiPaired') == 2
    np.testing.assert_allclose(m.get_current_measurement('NucleiPaired', 'Location_Center_X'), [1.5, 5.5])
    np.testing.assert_allclose(m.get_current_measurement('NucleiPaired', 'Location_Center_Y'), [1.5, 4.0])
    np.testing.assert_array_equal(m.get_current_measurement('NucleiPaired', 'Number_Object_Number'), [1, 2])


@pytest.mark.parametrize(
    'metadata, files, message',
    [
        (dict(METADATA, Acquisition='A01_s2'), FILES, 'not NucleiPaired'),
        (dict(METADATA, Batch='batch_0002'), FILES, 'not NucleiPaired'),
        (METADATA, dict(FILES, DNA=('other.tiff', '/raw/P1')), 'was made from DNA'),
        (METADATA, dict(FILES, IllumDNA=('IllumDNA.npy', '/illum/P2')), 'was made from IllumDNA'),
    ],
)
def test_loader_refuses_a_mask_of_another_image_set(tmp_path, metadata, files, message):
    """A mask is used only for the image set and the exact files that made it."""
    segmentation_mask(tmp_path, np.ones((4, 4)), metadata=metadata, files=files)
    work = workspace(tmp_path, METADATA, FILES, np.zeros((4, 4)))
    with pytest.raises(ValueError, match=message):
        loader().run(work)


def test_loader_refuses_a_mask_of_another_size(tmp_path):
    """A mask must have the size of its input image."""
    segmentation_mask(tmp_path, np.ones((4, 4)))
    with pytest.raises(ValueError, match='shape'):
        loader().run(workspace(tmp_path, METADATA, FILES, np.zeros((4, 5))))


# ---------------------------------------------------------------------------------------------
# RunCellpose -> SaveLabelMasks -> LoadLabelMasks gives the same objects as RunCellpose
# ---------------------------------------------------------------------------------------------


def model_available():
    """True if the cpsam model file is on this computer (Cellpose would otherwise download 1.2 GB)."""
    folder = os.environ.get('CELLPOSE_LOCAL_MODELS_PATH') or Path.home() / '.cellpose' / 'models'
    return (Path(folder) / 'cpsam').is_file()


@pytest.mark.skipif(not model_available(), reason='cpsam model file not found; set CELLPOSE_LOCAL_MODELS_PATH')
def test_loaded_objects_equal_cellpose_objects(tmp_path):
    """Oracle: Cellpose-SAM finds the 3 bright disks. The saved and loaded objects are the same objects.

    This is the round trip between SEGMENT and ANALYSIS, on the CPU, with the vendored plugin.
    """
    from runcellpose import RunCellpose
    from savelabelmasks import SaveLabelMasks

    # Three disks of radius 10 on a dark background, with seeded noise.
    yy, xx = np.mgrid[:128, :128]
    image = np.random.default_rng(0).normal(0.05, 0.01, (128, 128))
    for cy, cx in ((32, 32), (40, 96), (96, 64)):
        image[(yy - cy) ** 2 + (xx - cx) ** 2 <= 100] = 0.8
    image = image.clip(0, 1)

    # SEGMENT: RunCellpose, then SaveLabelMasks into <tmp>/segmentation (the Default Output Folder).
    # SaveLabelMasks traces CorrDNA back to DNA and IllumDNA through the modules of the pipeline.
    pipeline = load_pipeline(EXAMPLE / '2_analysis.cppipe')
    cellpose = pipeline.modules()[7]
    assert isinstance(cellpose, RunCellpose)
    work = workspace(tmp_path, METADATA, FILES, image, pipeline)
    cellpose.run(work)
    found = work.object_set.get_objects('NucleiPaired').segmented
    assert found.max() == 3

    from cellprofiler_core.preferences import set_default_output_directory

    (tmp_path / 'segmentation').mkdir()
    set_default_output_directory(str(tmp_path / 'segmentation'))
    saver = SaveLabelMasks()
    saver.set_module_num(100)
    saver.run(work)

    # ANALYSIS: a new workspace for the same image set loads the same objects and measurements.
    again = workspace(tmp_path, METADATA, FILES, image)
    loader().run(again)
    np.testing.assert_array_equal(again.object_set.get_objects('NucleiPaired').segmented, found)
    for feature in ('Location_Center_X', 'Location_Center_Y', 'Number_Object_Number'):
        np.testing.assert_array_equal(
            again.measurements.get_current_measurement('NucleiPaired', feature),
            work.measurements.get_current_measurement('NucleiPaired', feature),
        )
