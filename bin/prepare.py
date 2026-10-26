#!/usr/bin/env python3
"""PREPARE step: turn a folder of TIFFs and two pipelines into a plan for the run.

The step runs once, before any CellProfiler task. It checks all inputs, so a problem stops the
run in seconds instead of after hours.

Data in:  every TIFF path (Nextflow stages them as tracked*/), the --configs folder, the batch size.
Data out: the folder 'prepared'. Nextflow publishes it to logs/run_inputs/. It holds:
  plan.json                            the plates, their images and their batches
  manifests/<plate>/illumination.csv   every image set of the plate (CellProfiler LoadData format)
  manifests/<plate>/batch_NNNN.csv     the image sets of one batch
  pipelines/illumination.cppipe        working copy of 1_illumination.cppipe
  pipelines/analysis.cppipe            working copy of 2_analysis.cppipe
  pipelines/contract.json              facts that the later steps check against

The original .cppipe files do not change.
"""
import argparse
import csv
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from cp_inputs import read_config, validate_images


def write_csv(path, rows):
    """Write a list of dicts to a CSV file. The columns are sorted by name.

    Args:
        path: the CSV file to write. Missing folders are created.
        rows: a list of dicts that all have the same keys.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=sorted(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def load_pipeline(path):
    """Load a .cppipe file with CellProfiler.

    CellProfiler normally only warns when it cannot load a module. This function stops instead,
    so a broken pipeline never runs.

    Args:
        path: the .cppipe file.

    Returns:
        The CellProfiler Pipeline object.

    Raises:
        ValueError: if CellProfiler cannot load a module.
    """
    from cellprofiler_core.pipeline import Pipeline
    from cellprofiler_core.pipeline.event import LoadException
    pipeline = Pipeline()
    def listener(pipeline, event):
        """Turn a CellProfiler load warning into an error."""
        if isinstance(event, LoadException):
            raise ValueError(f'{path}: {event.module_name}: {event.error}')
    pipeline.add_listener(listener)
    pipeline.load(str(path))
    return pipeline


def adapt(config_dir, output):
    """Write the working copies of the two pipelines and return the contract.

    Changes to both copies:
      - One LoadData module replaces the four input modules (Images, Metadata, NamesAndTypes,
        Groups). LoadData reads the manifest of a task, so each task sees only its own files.
    Changes to the analysis copy only:
      - ExportToSpreadsheet exports every measurement to features/<Object>.csv.
      - SaveLabelMasks (plugins/) runs before the export and saves one uint32 mask per object.
    Checks, without changes:
      - The illumination pipeline adds up all image sets of the plate and saves .npy files at the end.
      - The analysis pipeline applies the same functions before it finds any objects.
      - No module needs data from other batches.
    Segmentation and measurement settings stay the same.

    Args:
        config_dir: the --configs folder.
        output: the folder for the working copies (prepared/pipelines).

    Returns:
        The contract dict: object names, illumination functions, cell compartments, versions.

    Raises:
        ValueError: if a pipeline breaks one of the checks above.
    """

    # The checks below know CellProfiler 4.2.8.1 exactly. Another version may behave differently.
    import importlib.metadata
    for package in ('cellprofiler', 'cellprofiler-core'):
        if importlib.metadata.version(package) != '4.2.8.1':
            raise ValueError(f'Require {package}=4.2.8.1 from environment.yml')
    from cellprofiler_core.preferences import set_headless, set_plugin_directory
    set_headless()
    set_plugin_directory(str(Path('plugins').resolve()))
    from cellprofiler_core.pipeline import Pipeline
    from cellprofiler_core.modules.loaddata import LoadData
    from cellprofiler_core.setting.text import Directory
    from cellprofiler_core.constants.measurement import IMAGE
    import sys
    sys.path.insert(0, str(Path('plugins').resolve()))
    from savelabelmasks import SaveLabelMasks
    report = {'objects': [], 'corrections': {}, 'changes': [],
              'versions': {p: importlib.metadata.version(p) for p in
                           ('cellprofiler', 'cellprofiler-core', 'numpy', 'scipy', 'scikit-image', 'tifffile')}}
    for kind, filename in [('illumination', '1_illumination.cppipe'), ('analysis', '2_analysis.cppipe')]:
        source = load_pipeline(config_dir / filename)
        modules = source.modules()
        if kind == 'analysis':

            # Modules after the 4 input modules must work on each image set alone.
            for module in modules[4:]:
                if module.is_aggregation_module() or module.module_name in {'TrackObjects', 'CreateBatchFiles', 'FlagImage'}:
                    raise ValueError(f'{module.module_name} requires group/cycle review before independent batching')

            # Classic segmentation: nuclei first, then cells grown from them with a watershed.
            primary = [m for m in modules if m.module_name == 'IdentifyPrimaryObjects']
            secondary = [m for m in modules if m.module_name == 'IdentifySecondaryObjects']
            if not primary or not secondary or any(m.method.value not in {'Watershed - Gradient', 'Watershed - Image'} for m in secondary):
                raise ValueError('Analysis must use traditional nuclei detection and watershed secondary objects')
            if any(m.watershed_method.value not in {'Intensity', 'Shape'} or m.unclump_method.value == 'None' for m in primary):
                raise ValueError('Primary objects must enable watershed declumping')

            # The illumination correction must happen before segmentation.
            apply = [m for m in modules if m.module_name == 'CorrectIlluminationApply']
            if len(apply) != 1 or modules.index(apply[0]) > modules.index(primary[0]):
                raise ValueError('Apply plate illumination before segmentation')
            for image in apply[0].images:
                report['corrections'][image.illum_correct_function_image_name.value] = image.image_name.value

            # The per-cell table joins cytoplasm and nuclei onto cells, as the tertiary module defines them.
            tertiary = [m for m in modules if m.module_name == 'IdentifyTertiaryObjects']
            if len(tertiary) != 1:
                raise ValueError('A per-cell feature table requires exactly one IdentifyTertiaryObjects module')
            report['compartments'] = dict(cells=tertiary[0].secondary_objects_name.value,
                                          nuclei=tertiary[0].primary_objects_name.value,
                                          cytoplasm=tertiary[0].subregion_objects_name.value)
        else:

            # Each calculated function must be saved once, as .npy, after the last image set.
            calculations = [m for m in modules if m.module_name == 'CorrectIlluminationCalculate']
            saves = [m for m in modules if m.module_name == 'SaveImages']
            if not calculations or len(calculations) != len(saves):
                raise ValueError('Require exactly one saved illumination function per calculation')
            expected = {m.illumination_image_name.value: m.image_name.value for m in calculations}
            if len(expected) != len(calculations):
                raise ValueError('Duplicate illumination function names')
            if any(m.each_or_all.value != 'All: Across cycles' or m.show_window or m.save_average_image.value or m.save_dilated_image.value for m in calculations):
                raise ValueError('Illumination must accumulate across cycles without intermediate calculation/display')
            for module in saves:
                if module.when_to_save.value != 'Last cycle' or module.file_format.value != 'npy':
                    raise ValueError('Illumination must save NPY functions on the last cycle')
                if module.image_name.value not in expected or module.single_file_name.value != module.image_name.value:
                    raise ValueError('Illumination save names must match calculation image names')

                # Save into the task's own output folder.
                module.pathname.value = 'Default Output Folder|'
            report['calculated'] = expected

        # Build the working copy: LoadData first, then every module after the 4 input modules.
        result = Pipeline()
        loader = LoadData()
        loader.csv_directory.value = 'Default Input Folder|'
        loader.csv_file_name.value = 'load_data.csv'
        loader.rescale.value = True
        active = [loader] + modules[4:]
        if kind == 'analysis':

            # Export every table to features/, and save the masks just before the export.
            exporters = [m for m in active if m.module_name == 'ExportToSpreadsheet']
            if len(exporters) != 1:
                raise ValueError('Require one ExportToSpreadsheet module')
            exporter = exporters[0]
            exporter.wants_everything.value = True
            exporter.wants_prefix.value = False
            exporter.directory.value = 'Default Output Folder sub-folder|features'
            active.insert(active.index(exporter), SaveLabelMasks())
        for i, module in enumerate(active, 1):
            module.set_module_num(i)
            module.show_window = False
            if kind == 'analysis':

                # External destinations could collide across workers. Preserve relative output subfolders.
                for item in module.settings():
                    if isinstance(item, Directory) and item.value.startswith('Elsewhere...|') and item.value != 'Elsewhere...|':
                        raise ValueError(f'{module.module_name}: absolute output destination requires review: {item.value}')
            result.add_module(module)
        if kind == 'analysis':

            # Every object type that CellProfiler counts gets a mask and a table.
            for module in active[1:]:
                for obj, feature, *_ in module.get_measurement_columns(result):
                    if obj == IMAGE and feature.startswith('Count_'):
                        report['objects'].append(feature[len('Count_'):])
            report['objects'] = sorted(set(report['objects']))
            if not report['objects']:
                raise ValueError('No object counts defined by analysis pipeline')
            if any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', name) for name in report['objects']):
                raise ValueError('Object names must be safe filename components')

        # Write the copy, then load it again to prove CellProfiler accepts it.
        with (output / f'{kind}.cppipe').open('w') as stream:
            result.dump(stream)
        load_pipeline(output / f'{kind}.cppipe')

    # The analysis must apply exactly the functions that the illumination step makes.
    if report['calculated'] != report['corrections']:
        raise ValueError(f'Calculated and applied illumination functions differ: {report}')
    if not set(report['compartments'].values()) <= set(report['objects']):
        raise ValueError(f'Cell compartments are not exported objects: {report["compartments"]}')
    report['changes'] = ['Replace input modules with generated LoadData manifests',
                         'Keep across-cycle illumination and last-cycle NPY exports',
                         'Export all object tables and uint32 label masks; use batch-local destinations',
                         'Realign CP 4.2.8.1 AreaShape/Texture rows shifted by objects without pixels']
    return report


def prepare(config_dir, paths, batch_size, destination):
    """Check the images, write the manifests and plan.json, then write the pipeline copies.

    A batch is a run of consecutive image sets from one plate. A batch never splits the
    channels of an image set and never mixes plates.

    Args:
        config_dir: the --configs folder.
        paths: all TIFF paths of the run.
        batch_size: the number of image sets per analysis batch.
        destination: the output folder ('prepared').
    """
    config = read_config(config_dir)
    image_sets = validate_images(paths, config)
    destination.mkdir(parents=True, exist_ok=True)
    pipelines = destination / 'pipelines'
    pipelines.mkdir(exist_ok=True)

    # Turn each image set into one LoadData row and sort the rows by plate.
    plates = defaultdict(list)
    names = set()
    for row in image_sets:
        metadata = row['metadata']

        # The acquisition key is the image name that all channel files share, e.g. A02_s1_x0_y0.
        # Masks are named <acquisition>_<Object>.tiff and the CSVs carry it as Metadata_Acquisition.
        acquisition = row['name']
        if len(acquisition) > 150 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', acquisition):
            raise ValueError(f'Unsafe or overly long image name: {acquisition!r}')
        if (metadata['Plate'], acquisition) in names:
            raise ValueError(f'Two image sets in plate {metadata["Plate"]} share the image name {acquisition}')
        names.add((metadata['Plate'], acquisition))

        # One LoadData row: Metadata_* columns plus FileName_/PathName_ for each channel image.
        values = {'Metadata_' + k: v for k, v in metadata.items()}
        values['Metadata_Acquisition'] = acquisition
        for channel, filename in row['images'].items():
            name = config['channels'][channel]
            values['FileName_' + name] = Path(filename).name
            values['PathName_' + name] = str(Path(filename).parent)
        plates[metadata['Plate']].append((values, list(row['images'].values())))

    # For each plate: one manifest with all image sets (illumination), then one per batch (analysis).
    plan = []
    for plate, rows in sorted(plates.items()):
        complete = [dict(row, Metadata_Batch='illumination') for row, _ in rows]
        illum_csv = destination / 'manifests' / plate / 'illumination.csv'
        write_csv(illum_csv, complete)
        jobs = []
        for start in range(0, len(rows), batch_size):
            batch = f'batch_{start // batch_size + 1:04d}'
            selected = rows[start:start + batch_size]
            csv_path = destination / 'manifests' / plate / f'{batch}.csv'
            write_csv(csv_path, [dict(row, Metadata_Batch=batch) for row, _ in selected])
            jobs.append(dict(batch=batch, manifest=str(csv_path.relative_to(destination)),
                             images=[p for _, paths in selected for p in paths], sets=len(selected)))
        plan.append(dict(plate=plate, manifest=str(illum_csv.relative_to(destination)),
                         images=[p for _, paths in rows for p in paths], batches=jobs, sets=len(rows)))

    # Write the pipeline copies and the contract. Record input sizes and pipeline checksums for the logs.
    report = adapt(config_dir, pipelines)
    report.update(config)
    report['image_sets'] = len(image_sets)
    report['input_fingerprints'] = {str(p): {'size': Path(p).stat().st_size, 'mtime_ns': Path(p).stat().st_mtime_ns} for p in sorted(paths)}
    report['pipeline_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(config_dir.glob('*.cppipe'))}
    (destination / 'plan.json').write_text(json.dumps(plan, indent=2))
    (pipelines / 'contract.json').write_text(json.dumps(report, indent=2))
    print(f'Validated {len(image_sets)} image sets, {len(plates)} plates, {sum(len(p["batches"]) for p in plan)} batches')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--configs', type=Path, required=True)
    parser.add_argument('--batch-size', type=int, required=True)
    parser.add_argument('--images-list', type=Path)
    parser.add_argument('--out', type=Path, default=Path('prepared'))
    args = parser.parse_args()

    # Inside Nextflow the images are the staged tracked*/ links. For a manual test, pass a list file.
    paths = ([Path(p) for p in args.images_list.read_text().splitlines()] if args.images_list
             else [p.resolve() for p in sorted(Path('.').glob('tracked*/*'))])
    try:
        if args.batch_size < 1:
            raise ValueError('Batch size must be positive')
        prepare(args.configs, paths, args.batch_size, args.out)
    except (ValueError, StopIteration, KeyError) as error:
        parser.exit(2, f'Input/pipeline validation failed: {error}\n')
