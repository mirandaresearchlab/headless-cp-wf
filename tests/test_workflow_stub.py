"""Run the whole workflow (main.nf) with `nextflow run -stub` and check its channels (issue #14).

The stub: blocks of the processes write small stand-in outputs without CellProfiler. PREPARE still
checks the samplesheet and plans the batches for real (prepare.py --stub). Each later stub records
the plate, batch, group and illumination folder that it got. MERGE collects these records into
<plate>.parquet (a text file in a stub run). So the tests can check, for each batch:
  - it gets the illumination folder of its own plate (ILLUMINATION -> ANALYSIS),
  - with RunCellpose, it gets the SEGMENT folder of its own plate and batch (SEGMENT -> ANALYSIS),
  - it reaches the MERGE task of its plate exactly once (ANALYSIS -> MERGE),
and that a new run with --project writes into projects/<project>/ (issue #10).
--segmentation_only (issue #3) must stop after SEGMENT, and a later full run with -resume must
reuse ILLUMINATION and SEGMENT.

The tests need Nextflow and Java, and are skipped without them. They do not need CellProfiler.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import tifffile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'bin'))
from cp_inputs import read_config  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which('nextflow') or not shutil.which('java'), reason='needs Nextflow and Java')

# Plate P1 has 3 image sets and P2 has 2. With --batch_size 2: P1 has 2 batches, P2 has 1.
PLATES = {'P1': [('A02', 1), ('A02', 2), ('B03', 1)], 'P2': [('A02', 1), ('C04', 1)]}
BATCH_SIZE = 2
# SEGMENT on CPUs, one task per group of 2 batches.
CELLPOSE = ('--segmentation', 'cpu', '--segmentation_batches', '2', '--segmentation_workers', '1')


def samplesheet(folder, configs):
    """Write tiny TIFFs for PLATES with the channels of the pipelines, and their samplesheet."""
    channels = sorted(read_config(configs)['channels'].values())
    lines = ['plate,well,site,channel,path']
    for plate, sites in PLATES.items():
        for well, site in sites:
            for channel in channels:
                path = folder / 'images' / plate / f'{well}_{site}_{channel}.tif'
                path.parent.mkdir(parents=True, exist_ok=True)
                tifffile.imwrite(path, np.zeros((8, 8), dtype=np.uint16))
                lines.append(f'{plate},{well},{site},{channel},{path.relative_to(folder)}')
    sheet = folder / 'samplesheet.csv'
    sheet.write_text('\n'.join(lines) + '\n')
    return sheet


def run_stub(folder, configs, *extra, fail=False):
    """Run main.nf with -stub in folder, and return the project folder and the Nextflow output.

    The samplesheet and images are written only once per folder, so that -resume finds them unchanged.
    With fail=True, the run must fail instead of succeed.
    """
    sheet = folder / 'samplesheet.csv'
    if not sheet.exists():
        sheet = samplesheet(folder, configs)
    command = [
        'nextflow', '-q', 'run', str(ROOT), '-profile', 'local', '-stub',
        '--input', str(sheet), '--configs', str(configs), '--outdir', str(folder / 'out'),
        '--project', 'stubtest', '--batch_size', str(BATCH_SIZE), '--total_cpus', '2', '--task_memory', '1 GB',
        *extra,
    ]  # fmt: skip
    env = dict(os.environ, NXF_ANSI_LOG='false')
    result = subprocess.run(command, cwd=folder, env=env, capture_output=True, text=True, timeout=600)
    output = f'{result.stdout}\n{result.stderr}'
    assert (result.returncode != 0) == fail, f'{output}\n{(folder / ".nextflow.log").read_text()[-5000:]}'
    return folder / 'out' / 'projects' / 'stubtest', output


def task_status(project):
    """Process name -> set of task statuses (COMPLETED, CACHED, ...) from the trace of the last run."""
    lines = (project / 'report' / 'trace.txt').read_text().splitlines()
    header = lines[0].split('\t')
    statuses = {}
    for line in lines[1:]:
        row = dict(zip(header, line.split('\t')))
        statuses.setdefault(row['name'].split(':')[-1].split(' ')[0], set()).add(row['status'])
    return statuses


def records(project, plate):
    """The stub records of a plate's MERGE output: one dict per batch."""
    lines = (project / 'cp_features' / f'{plate}.parquet').read_text().splitlines()
    rows = []
    for line in lines:
        head, _, segmentation = line.partition(' segmentation=')
        row = dict(item.split('=', 1) for item in head.split())
        row['segmentation'] = segmentation.strip('[]')
        rows.append(row)
    return rows


def planned_batches(project):
    """Plate -> batch names, from the plan that PREPARE published."""
    plan = json.loads((project / 'logs' / 'run_inputs' / 'plan.json').read_text())
    return {p['plate']: [b['batch'] for b in p['batches']] for p in plan}


def check_common(project):
    """Checks for both configurations: output folder, plan, and the per-plate joins."""
    # Issue #10: a new run with --project writes into projects/<project>/, not a session-ID folder.
    assert sorted(p.name for p in project.parent.iterdir()) == ['stubtest']
    assert json.loads((project / 'run.json').read_text())['project'] == 'stubtest'

    batches = planned_batches(project)
    assert batches == {'P1': ['batch_0001', 'batch_0002'], 'P2': ['batch_0001']}
    for plate, names in batches.items():
        rows = records(project, plate)
        # Each batch of the plate reaches its plate's MERGE exactly once, with its own manifest
        # and the illumination folder of its own plate.
        assert sorted(r['batch'] for r in rows) == names
        for row in rows:
            assert row['plate'] == plate
            assert row['manifest'] == f'{row["batch"]}.csv'
            assert row['illumination'] == plate
        assert sorted(p.name for p in (project / 'masks' / plate).glob('*.tiff')) == [f'{plate}_{b}_stub.tiff' for b in names]
        assert (project / 'illum' / plate / 'plate.txt').read_text().strip() == plate
    return batches


def test_classic_pipeline_runs_from_start_to_end(tmp_path):
    """cp-configs: no RunCellpose, so no SEGMENT task, and ANALYSIS gets no SEGMENT folder.
    An explicit --segmentation_only false (text on the command line) must mean false."""
    project, _ = run_stub(tmp_path, ROOT / 'cp-configs', '--segmentation_only', 'false')
    check_common(project)
    for plate in PLATES:
        assert {r['segmentation'] for r in records(project, plate)} == {'none'}


def test_cellpose_pipeline_joins_each_batch_to_its_segment_folder(tmp_path):
    """cp-configs-cellpose: SEGMENT runs per group of 2 batches. Each batch gets the SEGMENT folder
    of its own plate and batch, made with its own plate's illumination."""
    project, _ = run_stub(tmp_path, ROOT / 'cp-configs-cellpose', *CELLPOSE)
    batches = check_common(project)
    for plate in PLATES:
        for row in records(project, plate):
            segment = dict(item.split('=', 1) for item in row['segmentation'].split())
            assert segment == dict(plate=plate, group='segment_0001', batch=row['batch'], illumination=plate)
    assert len(batches['P1']) == 2  # so P1 really has a group of two batches in one SEGMENT task


def test_segmentation_only_stops_after_segment_and_resume_reuses_it(tmp_path):
    """--segmentation_only publishes the SEGMENT masks and runs no ANALYSIS or MERGE. A later
    full run with -resume reuses ILLUMINATION and SEGMENT and only measures."""
    project, _ = run_stub(tmp_path, ROOT / 'cp-configs-cellpose', *CELLPOSE, '--segmentation_only')
    assert not (project / 'cp_features').exists()
    assert set(task_status(project)) == {'PREPARE', 'ILLUMINATION', 'SEGMENT'}
    batches = planned_batches(project)
    for plate, names in batches.items():
        # One folder per batch, as SEGMENT wrote it: masks/, mask_manifest.csv and the stub record.
        assert sorted(p.name for p in (project / 'masks' / plate).iterdir()) == names
        for batch in names:
            folder = project / 'masks' / plate / batch
            assert [p.name for p in (folder / 'masks').iterdir()] == [f'{plate}_{batch}_segment_stub.tiff']
            assert (folder / 'mask_manifest.csv').exists()
            assert f'plate={plate} group=segment_0001 batch={batch}' in (folder / 'stub.txt').read_text()

    project, _ = run_stub(tmp_path, ROOT / 'cp-configs-cellpose', *CELLPOSE, '-resume')
    status = task_status(project)
    assert status['PREPARE'] == status['ILLUMINATION'] == status['SEGMENT'] == {'CACHED'}
    assert status['ANALYSIS'] == status['MERGE'] == {'COMPLETED'}
    check_common(project)


def test_segmentation_only_needs_runcellpose(tmp_path):
    """Without RunCellpose, segmentation is part of ANALYSIS, so --segmentation_only stops the run."""
    _, output = run_stub(tmp_path, ROOT / 'cp-configs', '--segmentation_only', fail=True)
    assert '--segmentation_only needs RunCellpose in 2_analysis.cppipe' in output


def task_scripts(folder):
    """The .command.run files of all tasks of a stub run. They hold the exported environment."""
    return [path.read_text() for path in (folder / 'work').glob('*/*/.command.run')]


def test_cellpose_models_variable_is_set_only_with_the_option(tmp_path):
    """Without --cellpose_models, no task gets CELLPOSE_LOCAL_MODELS_PATH, and Nextflow does not warn
    about an empty value once for every task. With the option, every task gets the folder."""
    without, with_option = tmp_path / 'without', tmp_path / 'with'
    for folder in (without, with_option):
        folder.mkdir()
    run_stub(without, ROOT / 'cp-configs-cellpose', *CELLPOSE)
    run_stub(with_option, ROOT / 'cp-configs-cellpose', *CELLPOSE, '--cellpose_models', '/some/folder')

    assert 'CELLPOSE_LOCAL_MODELS_PATH' not in (without / '.nextflow.log').read_text()
    scripts = task_scripts(without)
    assert scripts and not any('CELLPOSE_LOCAL_MODELS_PATH' in text for text in scripts)

    scripts = task_scripts(with_option)
    assert scripts and all('export CELLPOSE_LOCAL_MODELS_PATH="/some/folder"' in text for text in scripts)
