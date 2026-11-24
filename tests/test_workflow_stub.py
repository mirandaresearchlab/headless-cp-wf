"""Run the whole workflow (main.nf) with `nextflow run -stub` and check its channels (issue #14).

The stub: blocks of the processes write small stand-in outputs without CellProfiler. PREPARE still
checks the samplesheet and plans the batches for real (prepare.py --stub). Each later stub records
the plate, batch, group and illumination folder that it got. MERGE collects these records into
<plate>.parquet (a text file in a stub run). So the tests can check, for each batch:
  - it gets the illumination folder of its own plate (ILLUMINATION -> ANALYSIS),
  - with RunCellpose, it gets the SEGMENT folder of its own plate and batch (SEGMENT -> ANALYSIS),
  - it reaches the MERGE task of its plate exactly once (ANALYSIS -> MERGE),
and that a new run with --project writes into projects/<project>/ (issue #10).

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


def run_stub(folder, configs, *extra):
    """Run main.nf with -stub in folder, and return the project folder."""
    sheet = samplesheet(folder, configs)
    command = [
        'nextflow', '-q', 'run', str(ROOT), '-profile', 'local', '-stub',
        '--input', str(sheet), '--configs', str(configs), '--outdir', str(folder / 'out'),
        '--project', 'stubtest', '--batch_size', str(BATCH_SIZE), '--total_cpus', '2', '--task_memory', '1 GB',
        *extra,
    ]  # fmt: skip
    env = dict(os.environ, NXF_ANSI_LOG='false')
    result = subprocess.run(command, cwd=folder, env=env, capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, f'{result.stdout}\n{result.stderr}\n{(folder / ".nextflow.log").read_text()[-5000:]}'
    return folder / 'out' / 'projects' / 'stubtest'


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
        assert sorted(p.name for p in (project / 'masks' / plate).iterdir()) == [f'{plate}_{b}_stub.tiff' for b in names]
        assert (project / 'illum' / plate / 'plate.txt').read_text().strip() == plate
    return batches


def test_classic_pipeline_runs_from_start_to_end(tmp_path):
    """cp-configs: no RunCellpose, so no SEGMENT task, and ANALYSIS gets no SEGMENT folder."""
    project = run_stub(tmp_path, ROOT / 'cp-configs')
    check_common(project)
    for plate in PLATES:
        assert {r['segmentation'] for r in records(project, plate)} == {'none'}


def test_cellpose_pipeline_joins_each_batch_to_its_segment_folder(tmp_path):
    """cp-configs-cellpose: SEGMENT runs per group of 2 batches. Each batch gets the SEGMENT folder
    of its own plate and batch, made with its own plate's illumination."""
    project = run_stub(
        tmp_path, ROOT / 'cp-configs-cellpose', '--segmentation', 'cpu', '--segmentation_batches', '2', '--segmentation_workers', '1'
    )
    batches = check_common(project)
    for plate in PLATES:
        for row in records(project, plate):
            segment = dict(item.split('=', 1) for item in row['segmentation'].split())
            assert segment == dict(plate=plate, group='segment_0001', batch=row['batch'], illumination=plate)
    assert len(batches['P1']) == 2  # so P1 really has a group of two batches in one SEGMENT task
