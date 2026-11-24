#!/usr/bin/env python3
"""PREPARE step: turn a samplesheet and two pipelines into a plan for the run.

The step runs once, before any CellProfiler task. It checks all inputs, so a problem stops the
run in seconds instead of after hours.

Data in:  the samplesheet, every image file in it (Nextflow stages them as tracked*/), the
          --configs folder with the two .cppipe files, and the batch size.
Data out: the folder 'prepared'. Nextflow publishes it to logs/run_inputs/. It holds:
  samplesheet.csv                      one row per image file, with real paths
  plan.json                            the plates, their images and their batches
  manifests/<plate>/illumination.csv   every image set of the plate (CellProfiler LoadData format)
  manifests/<plate>/batch_NNNN.csv     the image sets of one batch
  pipelines/illumination.cppipe        working copy of 1_illumination.cppipe
  pipelines/analysis.cppipe            working copy of 2_analysis.cppipe
  pipelines/segmentation.cppipe        the RunCellpose part of 2_analysis.cppipe (only if it has RunCellpose)
  pipelines/contract.json              facts that the later steps check against

The original .cppipe files do not change.
"""

import argparse
import hashlib
import importlib.metadata
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from cp_inputs import read_config, read_samplesheet, tiff_shape, write_csv, write_samplesheet

CELLPROFILER_VERSION = '4.2.8.1'

# RunCellpose runs in its own SEGMENT task (GPU or CPU). Only Cellpose-SAM (Cellpose 4) is supported,
# with the version of the RunCellpose Docker image cellprofiler/runcellpose_with_pretrained:4.0.6.
CELLPOSE = 'RunCellpose'
CELLPOSE_VERSION = '4.0.6'

# The first four modules of a CellProfiler pipeline read the images: Images, Metadata,
# NamesAndTypes and Groups. The working copies replace them with one LoadData module.
INPUT_MODULES = 4


def load_pipeline(path):
    """Load a .cppipe file with CellProfiler, and stop on any module that does not load.

    CellProfiler normally only warns when it cannot load a module. This function raises an
    error instead, so a broken pipeline never runs.

    Parameters
    ----------
    path : str or Path
        The .cppipe file.

    Returns
    -------
    cellprofiler_core.pipeline.Pipeline
        The loaded pipeline.

    Raises
    ------
    ValueError
        If CellProfiler cannot load a module.
    """
    from cellprofiler_core.pipeline import Pipeline
    from cellprofiler_core.pipeline.event import LoadException

    def listener(pipeline, event):
        if isinstance(event, LoadException):
            raise ValueError(f'{path}: {event.module_name}: {event.error}')

    pipeline = Pipeline()
    pipeline.add_listener(listener)
    pipeline.load(str(path))
    return pipeline


def check_illumination(modules):
    """Check the illumination pipeline, and make it save into the task folder.

    Each correction function must add up all image sets of the plate ("All: Across cycles"),
    and the pipeline must save it once, as .npy, after the last image set.

    Parameters
    ----------
    modules : list
        The CellProfiler modules of ``1_illumination.cppipe``. The SaveImages modules are
        changed in place to save into the default output folder.

    Returns
    -------
    dict
        Name of each correction function -> the image it is calculated from, e.g.
        ``{"IllumDNA": "DNA"}``.

    Raises
    ------
    ValueError
        If a function is not saved exactly once as .npy on the last cycle, or is calculated per
        image set.
    """
    calculations = [m for m in modules if m.module_name == 'CorrectIlluminationCalculate']
    saves = [m for m in modules if m.module_name == 'SaveImages']
    if not calculations or len(calculations) != len(saves):
        raise ValueError('Require exactly one saved illumination function per calculation')
    calculated = {m.illumination_image_name.value: m.image_name.value for m in calculations}
    if len(calculated) != len(calculations):
        raise ValueError('Duplicate illumination function names')
    if any(
        m.each_or_all.value != 'All: Across cycles' or m.show_window or m.save_average_image.value or m.save_dilated_image.value
        for m in calculations
    ):
        raise ValueError('Illumination must accumulate across cycles without intermediate calculation/display')
    for module in saves:
        if module.when_to_save.value != 'Last cycle' or module.file_format.value != 'npy':
            raise ValueError('Illumination must save NPY functions on the last cycle')
        if module.image_name.value not in calculated or module.single_file_name.value != module.image_name.value:
            raise ValueError('Illumination save names must match calculation image names')
        module.pathname.value = 'Default Output Folder|'
    return calculated


def check_analysis(modules):
    """Check that the analysis pipeline can run on independent batches.

    Parameters
    ----------
    modules : list
        The CellProfiler modules of ``2_analysis.cppipe``.

    Returns
    -------
    corrections : dict
        Name of each applied correction function -> the image it corrects.
    compartments : dict
        The object names that the per-cell table joins: ``cells``, ``nuclei`` and ``cytoplasm``,
        from the one IdentifyTertiaryObjects module.

    Raises
    ------
    ValueError
        If a module needs data from other image sets, there is no supported segmentation (see
        below), the correction is applied after the segmentation, or there is not exactly one
        IdentifyTertiaryObjects module.

    Notes
    -----
    Supported segmentation: classic nuclei first (IdentifyPrimaryObjects with declumping), then
    cells grown from them with a watershed or propagation; or RunCellpose (Cellpose-SAM) for any
    of the objects. IdentifyPrimaryObjects and IdentifySecondaryObjects keep their rules when
    they are used together with RunCellpose.
    """
    for module in modules[INPUT_MODULES:]:
        if module.is_aggregation_module() or module.module_name in {'TrackObjects', 'CreateBatchFiles', 'FlagImage'}:
            raise ValueError(f'{module.module_name} requires group/cycle review before independent batching')

    primary = [m for m in modules if m.module_name == 'IdentifyPrimaryObjects']
    secondary = [m for m in modules if m.module_name == 'IdentifySecondaryObjects']
    cellpose = [m for m in modules if m.module_name == CELLPOSE]
    if not cellpose and (not primary or not secondary):
        raise ValueError('Analysis must use traditional nuclei detection and watershed or propagation secondary objects, or RunCellpose')
    if any(m.method.value not in {'Watershed - Gradient', 'Watershed - Image', 'Propagation'} for m in secondary):
        raise ValueError('Secondary objects must use watershed or propagation')
    if any(m.watershed_method.value not in {'Intensity', 'Shape'} or m.unclump_method.value == 'None' for m in primary):
        raise ValueError('Primary objects must enable watershed declumping')

    # The illumination correction must happen before the first segmentation module.
    first = min(modules.index(m) for m in primary + cellpose)
    apply = [m for m in modules if m.module_name == 'CorrectIlluminationApply']
    if len(apply) != 1 or modules.index(apply[0]) > first:
        raise ValueError('Apply plate illumination before segmentation')
    corrections = {image.illum_correct_function_image_name.value: image.image_name.value for image in apply[0].images}

    # The per-cell table joins cytoplasm and nuclei onto cells, as the tertiary module defines them.
    tertiary = [m for m in modules if m.module_name == 'IdentifyTertiaryObjects']
    if len(tertiary) != 1:
        raise ValueError('A per-cell feature table requires exactly one IdentifyTertiaryObjects module')
    compartments = dict(
        cells=tertiary[0].secondary_objects_name.value,
        nuclei=tertiary[0].primary_objects_name.value,
        cytoplasm=tertiary[0].subregion_objects_name.value,
    )
    return corrections, compartments


def adaptive_windows(modules):
    """Return the adaptive threshold windows that CellProfiler will use.

    A module uses its window only if it is enabled and thresholds with the Adaptive strategy.
    CellProfiler does not split the image into window blocks for the Sauvola method, for
    IdentifyPrimaryObjects without advanced settings, or for IdentifySecondaryObjects with
    Distance - N.

    Parameters
    ----------
    modules : list
        The CellProfiler modules of a pipeline.

    Returns
    -------
    list of tuple
        One ``(module label, window size in pixels)`` per module, e.g.
        ``[("IdentifySecondaryObjects #9", 501)]``.
    """
    # iterate over all modules, not just the ones that are known to use adaptive thresholds,
    # so that any future modules that use adaptive thresholds are also checked.
    windows = []
    for module in modules:
        # set settings to the module's threshold settings if they exist, otherwise None
        settings = module if hasattr(module, 'adaptive_window_size') else getattr(module, 'threshold', None)

        # if the module is disabled, or does not have an adaptive_window_size setting, skip it
        if not module.enabled or settings is None or not hasattr(settings, 'adaptive_window_size'):
            continue
        # if the module is a basic module, skip it
        if getattr(module, 'basic', False):
            continue
        # if the module is IdentifySecondaryObjects and uses Distance - N, skip it
        if module.module_name == 'IdentifySecondaryObjects' and module.method.value == 'Distance - N':
            continue
        # threshold_operation is the method of the selected strategy, as a string.
        if settings.threshold_scope.value == 'Adaptive' and settings.threshold_operation != 'Sauvola':
            windows.append((f'{module.module_name} #{module.module_num}', settings.adaptive_window_size.value))
    return windows


def check_adaptive_windows(windows, shapes):
    """Check that each adaptive threshold window fits the images of every plate.

    CellProfiler 4.2.8.1 splits the image into blocks of the window size and stops with "Adaptive
    window cannot exceed 50% of an image dimension" if a side holds fewer than two blocks. This
    check applies the same rule in PREPARE, so the run stops before ILLUMINATION and not in
    ANALYSIS.

    Parameters
    ----------
    windows : list of tuple
        ``(module label, window size)`` from ``adaptive_windows()``.
    shapes : dict
        Plate -> image shape ``(rows, columns)``. All images of a plate share one shape.

    Raises
    ------
    ValueError
        If a side of the images of a plate is less than twice a window.
    """
    # iterate over the plates in sorted order, so that the error messages are deterministic
    # for each module that uses an adaptive threshold window, check if the window fits the image shape
    for plate, shape in sorted(shapes.items()):
        for label, window in windows:
            if any(side // window < 2 for side in shape):
                raise ValueError(
                    f'{label} uses an adaptive threshold window of {window} pixels, but the images of plate '
                    f'{plate} are {shape[0]} x {shape[1]} pixels. The window must be at most half of the '
                    f'shorter side ({min(shape) // 2} pixels). Use larger images, or a smaller "Size of '
                    f'adaptive window" in the pipeline'
                )


def check_cellpose(module):
    """Check that a RunCellpose module can run headless as Cellpose-SAM in a SEGMENT task.

    Parameters
    ----------
    module : RunCellpose
        A RunCellpose module of ``2_analysis.cppipe``.

    Returns
    -------
    dict or None
        For a custom model: its path, size and modification time, for the contract. Else None.

    Raises
    ------
    ValueError
        If the module is not Cellpose-SAM (v4), is 3D, saves a probability image, or uses a
        custom model that is not a file in an absolute folder.
    """
    name = module.y_name.value
    if module.cellpose_version.value != 'v4':
        raise ValueError(f'RunCellpose {name}: select Cellpose version v4 (Cellpose-SAM); the environment has cellpose {CELLPOSE_VERSION}')
    if module.do_3D.value:
        raise ValueError(f'RunCellpose {name}: 3D is not supported; the workflow reads 2D images')

    # Only the objects go from SEGMENT to ANALYSIS, so no later module may use other outputs.
    if module.save_probabilities.value:
        raise ValueError(
            f'RunCellpose {name}: set "Save probability image?" to No; the probability image is not passed from SEGMENT to ANALYSIS'
        )
    if module.mode_v4.value != 'custom':
        return None

    # A task reads a custom model from its own folder, so the folder must be absolute.
    choice, folder = module.model_directory.dir_choice, module.model_directory.custom_path
    if choice != 'Elsewhere...' or not Path(folder).is_absolute():
        raise ValueError(f'RunCellpose {name}: a custom model must be in an absolute folder ("Elsewhere..."), not {choice}')
    model = Path(folder) / module.model_file_name.value
    if not model.is_file():
        raise ValueError(f'RunCellpose {name}: custom model file not found: {model}')
    return {'path': str(model), 'size': model.stat().st_size, 'mtime_ns': model.stat().st_mtime_ns}


def split_segmentation(modules):
    """Split the analysis modules into the SEGMENT part and the ANALYSIS part.

    SEGMENT runs each RunCellpose module and the modules that make its input images (for example
    CorrectIlluminationApply), in pipeline order. ANALYSIS runs every module, with a LoadLabelMasks
    module (from plugins/) in place of each RunCellpose module: same position, same input images,
    same object name. LoadLabelMasks reads the masks that SEGMENT saved.

    Parameters
    ----------
    modules : list
        The modules of ``2_analysis.cppipe`` after the four input modules. The RunCellpose modules
        are changed in place: Python mode, model kept between image sets, GPU off. SEGMENT turns
        the GPU on at run time.

    Returns
    -------
    segmentation : list
        The modules of SEGMENT. Empty if there is no RunCellpose module.
    analysis : list
        The modules of ANALYSIS.
    objects : list of str
        The objects that RunCellpose makes, in pipeline order.

    Raises
    ------
    ValueError
        If a RunCellpose module fails ``check_cellpose()``, or its input depends on objects that
        another kind of module makes (SEGMENT would have to run that segmentation too).
    """
    from cellprofiler_core.setting.text import LabelName
    from loadlabelmasks import LoadLabelMasks
    from savelabelmasks import INPUTS, names, producers

    cellpose = [m for m in modules if m.module_name == CELLPOSE]
    for module in cellpose:
        check_cellpose(module)

    # Walk back from the inputs of each RunCellpose module to the modules that make them.
    # Images that no module makes are the images of the LoadData manifest.
    made_by = producers(modules)
    needed = {id(m) for m in cellpose}
    todo = [name for m in cellpose for name in names(m.visible_settings(), INPUTS)]
    while todo:
        name = todo.pop()
        if name not in made_by or id(made_by[name][0]) in needed:
            continue
        module, inputs = made_by[name]
        if module.module_name != CELLPOSE and names(module.visible_settings(), (LabelName,)):
            raise ValueError(
                f'RunCellpose input {name} depends on objects of {module.module_name}; SEGMENT runs only RunCellpose and image modules'
            )
        needed.add(id(module))
        todo += inputs

    analysis = []
    for module in modules:
        if module.module_name == CELLPOSE:
            module.docker_or_python.value = 'Python'
            module.cache_model.value = True
            module.use_gpu.value = False
            loader = LoadLabelMasks()
            loader.x_name.value = module.x_name.value
            loader.y_name.value = module.y_name.value
            if module.supply_nuclei.value:
                loader.nuclei_image.value = module.nuclei_image.value
            module = loader
        analysis.append(module)
    segmentation = [m for m in modules if id(m) in needed]
    return segmentation, analysis, [m.y_name.value for m in cellpose]


def working_copy(kind, modules):
    """Build the working copy of a pipeline: LoadData first, then all modules after the inputs.

    The analysis copy also exports every measurement to ``features/<Object>.csv`` and saves one
    uint32 label mask per object type (SaveLabelMasks, from plugins/) just before the export.
    The segmentation copy saves the masks of its objects at the end.

    Parameters
    ----------
    kind : {'illumination', 'analysis', 'segmentation'}
        Which pipeline this is.
    modules : list
        The CellProfiler modules of the pipeline, without the four input modules.

    Returns
    -------
    cellprofiler_core.pipeline.Pipeline
        The working copy.

    Raises
    ------
    ValueError
        If the analysis pipeline does not have exactly one ExportToSpreadsheet module, or a
        module writes to an absolute folder (tasks could overwrite each other's files there).
    """
    from cellprofiler_core.modules.loaddata import LoadData
    from cellprofiler_core.pipeline import Pipeline
    from cellprofiler_core.setting.text import Directory
    from savelabelmasks import SaveLabelMasks

    loader = LoadData()
    loader.csv_directory.value = 'Default Input Folder|'
    loader.csv_file_name.value = 'load_data.csv'
    loader.rescale.value = True
    active = [loader] + modules
    if kind == 'segmentation':
        active.append(SaveLabelMasks())
    if kind == 'analysis':
        exporters = [m for m in active if m.module_name == 'ExportToSpreadsheet']
        if len(exporters) != 1:
            raise ValueError('Require one ExportToSpreadsheet module')
        exporter = exporters[0]
        exporter.wants_everything.value = True
        exporter.wants_prefix.value = False
        exporter.directory.value = 'Default Output Folder sub-folder|features'
        active.insert(active.index(exporter), SaveLabelMasks())

    pipeline = Pipeline()
    for number, module in enumerate(active, 1):
        module.set_module_num(number)
        module.show_window = False
        if kind != 'illumination' and module.module_name != CELLPOSE:
            for item in module.settings():
                if isinstance(item, Directory) and item.value.startswith('Elsewhere...|') and item.value != 'Elsewhere...|':
                    raise ValueError(f'{module.module_name}: absolute output destination requires review: {item.value}')
        pipeline.add_module(module)
    return pipeline


def counted_objects(pipeline):
    """Return the object types that the pipeline counts (``Count_<Object>`` in the Image table).

    Each of them gets a mask and a feature table, so the later steps can check all of them.

    Parameters
    ----------
    pipeline : cellprofiler_core.pipeline.Pipeline
        The analysis working copy.

    Returns
    -------
    list of str
        The object names, sorted.

    Raises
    ------
    ValueError
        If there is no counted object, or an object name is not safe as a file name.
    """
    from cellprofiler_core.constants.measurement import IMAGE

    objects = sorted(
        {
            feature[len('Count_') :]
            for module in pipeline.modules()[1:]
            for obj, feature, *_ in module.get_measurement_columns(pipeline)
            if obj == IMAGE and feature.startswith('Count_')
        }
    )
    if not objects:
        raise ValueError('No object counts defined by analysis pipeline')
    if any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', name) for name in objects):
        raise ValueError('Object names must be safe filename components')
    return objects


def adapt(config_dir, output, shapes=None):
    """Check both pipelines, write their working copies, and return the contract.

    Changes to the copies: one LoadData module replaces the four input modules, so each task
    reads only its own manifest. The analysis copy exports every table and saves label masks.
    If the analysis has RunCellpose modules, they go to a third copy, segmentation.cppipe, and the
    analysis copy loads their masks instead (see ``split_segmentation()``). Segmentation and
    measurement settings stay the same.

    Parameters
    ----------
    config_dir : Path
        The folder with ``1_illumination.cppipe`` and ``2_analysis.cppipe``.
    output : Path
        The folder for the working copies (``prepared/pipelines``).
    shapes : dict, optional
        Plate -> image shape ``(rows, columns)``. If given, every adaptive threshold window must
        fit these images (see ``check_adaptive_windows()``).

    Returns
    -------
    dict
        The contract: object names, correction functions, cell compartments, package versions.

    Raises
    ------
    ValueError
        If the CellProfiler version is wrong, or a pipeline fails one of the checks.
    """
    # The checks know CellProfiler 4.2.8.1 exactly. Another version may behave differently.
    for package in ('cellprofiler', 'cellprofiler-core'):
        if importlib.metadata.version(package) != CELLPROFILER_VERSION:
            raise ValueError(f'Require {package}={CELLPROFILER_VERSION} from environment.yml')
    from cellprofiler_core.preferences import set_headless, set_plugin_directory

    set_headless()
    set_plugin_directory(str(Path('plugins').resolve()))
    sys.path.insert(0, str(Path('plugins').resolve()))

    report = dict(
        objects=[],
        changes=[
            'Replace input modules with generated LoadData manifests',
            'Keep across-cycle illumination and last-cycle NPY exports',
            'Export all object tables and uint32 label masks; use batch-local destinations',
            'Realign CP 4.2.8.1 AreaShape/Texture rows shifted by objects without pixels',
        ],
        versions={
            p: importlib.metadata.version(p) for p in ('cellprofiler', 'cellprofiler-core', 'numpy', 'scipy', 'scikit-image', 'tifffile')
        },
    )
    copies = {}
    modules = load_pipeline(config_dir / '1_illumination.cppipe').modules()
    windows = adaptive_windows(modules)
    report['calculated'] = check_illumination(modules)
    copies['illumination'] = working_copy('illumination', modules[INPUT_MODULES:])

    modules = load_pipeline(config_dir / '2_analysis.cppipe').modules()
    report['corrections'], report['compartments'] = check_analysis(modules)
    windows += adaptive_windows(modules)
    report['adaptive_windows'] = dict(windows)
    if shapes:
        check_adaptive_windows(windows, shapes)
    segmentation, analysis, report['segmentation'] = split_segmentation(modules[INPUT_MODULES:])
    copies['analysis'] = working_copy('analysis', analysis)
    report['objects'] = counted_objects(copies['analysis'])
    if segmentation:
        if importlib.metadata.version('cellpose') != CELLPOSE_VERSION:
            raise ValueError(f'Require cellpose={CELLPOSE_VERSION} from environment.yml for RunCellpose')
        copies['segmentation'] = working_copy('segmentation', segmentation)
        report['versions'].update({p: importlib.metadata.version(p) for p in ('cellpose', 'torch')})
        report['models'] = [model for model in map(check_cellpose, (m for m in segmentation if m.module_name == CELLPOSE)) if model]
        report['changes'].append('Run RunCellpose in SEGMENT tasks; ANALYSIS loads its masks with LoadLabelMasks')

    # MERGE joins nuclei and cytoplasm to their cell by Parent_<Cells>, so both must have it.
    columns = {(obj, feature) for obj, feature, *_ in copies['analysis'].get_measurement_columns()}
    cells = report['compartments']['cells']
    for part in ('nuclei', 'cytoplasm'):
        if (report['compartments'][part], f'Parent_{cells}') not in columns:
            raise ValueError(
                f'{report["compartments"][part]} has no Parent_{cells} measurement; '
                f'relate it to {cells} (RelateObjects) so that MERGE can join it'
            )

    # Write each copy, then load it again to prove that CellProfiler accepts it.
    for kind, pipeline in copies.items():
        with (output / f'{kind}.cppipe').open('w') as stream:
            pipeline.dump(stream)
        load_pipeline(output / f'{kind}.cppipe')

    # The analysis must apply exactly the functions that the illumination step makes.
    if report['calculated'] != report['corrections']:
        raise ValueError(f'Calculated and applied illumination functions differ: {report}')
    if not set(report['compartments'].values()) <= set(report['objects']):
        raise ValueError(f'Cell compartments are not exported objects: {report["compartments"]}')
    return report


def plan_batches(image_sets, config, batch_size, destination):
    """Write the LoadData manifests of each plate and its batches, and return the plan.

    A batch is a run of consecutive image sets from one plate. A batch never splits the channels
    of an image set and never mixes plates.

    Parameters
    ----------
    image_sets : list of dict
        The image sets from ``cp_inputs.read_samplesheet()``.
    config : dict
        The rules from ``cp_inputs.read_config()``.
    batch_size : int
        The number of image sets per batch.
    destination : Path
        The 'prepared' folder. The manifests go to ``manifests/<plate>/``.

    Returns
    -------
    list of dict
        One dict per plate: plate, manifest, images, sets, and its batches (batch, manifest,
        images, sets). Paths of manifests are relative to ``destination``.

    Raises
    ------
    ValueError
        If an image set name is unsafe or too long, or two image sets of a plate share a name.
    """
    plates, names = defaultdict(list), set()
    for image_set in image_sets:
        plate, acquisition = image_set['metadata']['Plate'], image_set['name']

        # The image set name names the masks (<acquisition>_<Object>.tiff) and Metadata_Acquisition.
        if len(acquisition) > 150 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', acquisition):
            raise ValueError(f'Unsafe or overly long image name: {acquisition!r}')
        if (plate, acquisition) in names:
            raise ValueError(f'Two image sets in plate {plate} share the image name {acquisition}')
        names.add((plate, acquisition))

        # One LoadData row: Metadata_* columns plus FileName_ and PathName_ for each channel.
        row = {'Metadata_' + k: v for k, v in image_set['metadata'].items()}
        row['Metadata_Acquisition'] = acquisition
        for channel, filename in image_set['images'].items():
            name = config['channels'][channel]
            row['FileName_' + name] = Path(filename).name
            row['PathName_' + name] = str(Path(filename).parent)
        plates[plate].append((row, list(image_set['images'].values())))

    plan = []
    for plate, rows in sorted(plates.items()):
        folder = destination / 'manifests' / plate
        write_csv(folder / 'illumination.csv', [dict(row, Metadata_Batch='illumination') for row, _ in rows])
        batches = []
        for start in range(0, len(rows), batch_size):
            batch = f'batch_{start // batch_size + 1:04d}'
            selected = rows[start : start + batch_size]
            write_csv(folder / f'{batch}.csv', [dict(row, Metadata_Batch=batch) for row, _ in selected])
            batches.append(
                dict(
                    batch=batch,
                    manifest=str((folder / f'{batch}.csv').relative_to(destination)),
                    images=[p for _, paths in selected for p in paths],
                    sets=len(selected),
                )
            )
        plan.append(
            dict(
                plate=plate,
                manifest=str((folder / 'illumination.csv').relative_to(destination)),
                images=[p for _, paths in rows for p in paths],
                batches=batches,
                sets=len(rows),
            )
        )
    return plan


def prepare(config_dir, samplesheet, staged, batch_size, destination):
    """Check the inputs, then write the samplesheet, manifests, plan and pipeline copies.

    Parameters
    ----------
    config_dir : Path
        The folder with the two .cppipe files.
    samplesheet : Path
        The samplesheet CSV file.
    staged : list of Path
        The image files that Nextflow staged. An empty list skips this check (manual runs).
    batch_size : int
        The number of image sets per ANALYSIS task.
    destination : Path
        The output folder ('prepared').

    Raises
    ------
    ValueError
        If an input fails a check, or the staged files differ from the files of the samplesheet.
    """
    config = read_config(config_dir)
    image_sets = read_samplesheet(samplesheet, config)
    listed = {Path(p) for s in image_sets for p in s['images'].values()}

    # Nextflow must stage (and so track) exactly the files of the samplesheet.
    if staged:
        staged = {Path(p).resolve() for p in staged}
        if staged != listed:
            raise ValueError(
                f'Staged files differ from the samplesheet: {len(staged - listed)} extra, '
                f'{len(listed - staged)} missing, for example {sorted(staged ^ listed)[:3]}'
            )
    (destination / 'pipelines').mkdir(parents=True, exist_ok=True)
    write_samplesheet(destination / 'samplesheet.csv', image_sets, config)
    plan = plan_batches(image_sets, config, batch_size, destination)

    # The contract, plus input sizes and pipeline checksums for the logs. All images of a plate
    # share one shape (read_samplesheet() checks this), so the first image gives the plate shape.
    shapes = {}
    for image_set in image_sets:
        plate = image_set['metadata']['Plate']
        if plate not in shapes:
            shapes[plate] = tiff_shape(next(iter(image_set['images'].values())))
    contract = adapt(config_dir, destination / 'pipelines', shapes)
    contract.update(config)
    contract['image_sets'] = len(image_sets)
    contract['input_fingerprints'] = {str(p): {'size': p.stat().st_size, 'mtime_ns': p.stat().st_mtime_ns} for p in sorted(listed)}
    contract['pipeline_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(config_dir.glob('*.cppipe'))}
    (destination / 'plan.json').write_text(json.dumps(plan, indent=2))
    (destination / 'pipelines' / 'contract.json').write_text(json.dumps(contract, indent=2))
    print(f'Validated {len(image_sets)} image sets, {len(plan)} plates, {sum(len(p["batches"]) for p in plan)} batches')


def main():
    """Parse the arguments and run PREPARE. Exit with code 2 and one line on an input error."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--configs', type=Path, required=True)
    parser.add_argument('--samplesheet', type=Path, required=True)
    parser.add_argument('--batch-size', type=int, required=True)
    parser.add_argument('--out', type=Path, default=Path('prepared'))
    args = parser.parse_args()

    # Inside Nextflow the images are the staged tracked*/ links. A manual run has none.
    staged = sorted(Path('.').glob('tracked*/*'))
    try:
        if args.batch_size < 1:
            raise ValueError('Batch size must be positive')
        prepare(args.configs, args.samplesheet, staged, args.batch_size, args.out)
    except (ValueError, StopIteration, KeyError) as error:
        parser.exit(2, f'Input/pipeline validation failed: {error}\n')


if __name__ == '__main__':
    main()
