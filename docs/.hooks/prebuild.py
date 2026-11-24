"""Generate reference pages from repository source without importing workflow dependencies."""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESCRIPTIONS = {
    'input': 'Required samplesheet CSV with one row per image file. See file formats.',
    'configs': 'Required folder containing the two named pipeline files.',
    'project': 'Output project name. Defaults to the session ID. Existing names owned by another session fall back to that ID.',
    'outdir': 'Parent of projects/.',
    'batch_size': 'Positive number of complete image sets per analysis task.',
    'segmentation': 'Where SEGMENT runs RunCellpose (Cellpose-SAM): cpu or gpu. Used only if 2_analysis.cppipe has RunCellpose. ANALYSIS always runs on CPUs.',
    'segmentation_batches': 'Analysis batches in one SEGMENT task. 0: 16 with --segmentation gpu (larger groups keep a GPU busy), 1 with cpu.',
    'segmentation_workers': 'Positive number of CellProfiler processes in one SEGMENT task. On a GPU they share it: 4 keep an A100 80% busy, 8 about 89% (3.8 GB GPU memory each). On a CPU each gets one core and task_memory.',
    'cellpose_models': 'Folder with the Cellpose-SAM model file cpsam. Default: ~/.cellpose/models. A missing file is downloaded once (1.2 GB).',
    'task_cpus': 'CPU request for each task. Library threads remain limited to one.',
    'task_memory': 'Memory request for each task. Must be positive and no larger than total_memory, on either profile.',
    'task_time': 'Time limit for each task.',
    'total_cpus': 'Positive shared CPU budget for the local executor.',
    'total_memory': 'Shared memory budget for local execution. Also bounds task_memory during validation on both profiles.',
    'max_forks': 'Local per-process concurrency limit. Zero adds no limit beyond executor resources.',
    'max_jobs': 'Maximum submitted/active tasks managed by the Slurm executor.',
    'nf_work_dir': 'Work folder. Local default: launchDir/work. Berzelius default: shared_dir/nextflow-work.',
    'shared_dir': 'Berzelius root for the default work folder. Supply it or --nf_work_dir.',
    'slurm_partition': 'Slurm partition. Confirm access and the partition name with your cluster.',
    'slurm_account': 'Optional Slurm allocation account passed with --account.',
    'gpu_partition': 'Slurm partition for SEGMENT with --segmentation gpu. Each task requests one GPU.',
    'gpu_cpus': 'Cores of one SEGMENT task with --segmentation gpu: the cores that come with one GPU (16 on Berzelius Ampere, 14 on Hopper).',
    'max_gpus': 'Most SEGMENT tasks, and so GPUs, at the same time with --segmentation gpu on Slurm.',
    'max_retries': 'Retry limit for task exit statuses 137 (memory), 140 (time limit) or 143 (cancel). Each retry multiplies task_memory and task_time by the attempt number, up to the profile limit (local: total_memory; Berzelius: 960 GB and 72 hours).',
}


def params(path):
    """Return the parameter defaults of a config file, or an empty dict if it has no params block."""
    block = re.search(r'^params\s*\{(.*?)^\}', path.read_text(), re.M | re.S)
    return dict(re.findall(r'^\s*(\w+)\s*=\s*([^\n]+)', block.group(1), re.M)) if block else {}


def save(name, lines):
    path = ROOT / 'docs' / name
    content = '\n'.join(lines) + '\n'
    if not path.exists() or path.read_text() != content:
        path.write_text(content)


def generate():
    base = params(ROOT / 'nextflow.config')
    local = {**base, **params(ROOT / 'conf/local.config')}
    cluster = {**base, **params(ROOT / 'conf/berzelius.config')}
    if set(base) != set(DESCRIPTIONS):
        raise ValueError('Update documentation descriptions to match nextflow.config parameters')
    lines = [
        '# Workflow parameters',
        '',
        'This reference is generated from `nextflow.config` and both profile files on every documentation build.',
        '',
        'Use `--name value` for these parameters. `null` means no explicit value.',
        'Defaults below are configuration values. Descriptions explain path fallbacks and scope.',
        '',
        '| Parameter | Local default | Berzelius default | Meaning |',
        '|---|---|---|---|',
    ]
    for key in base:
        lines.append(f'| `--{key}` | `{local[key].strip()}` | `{cluster[key].strip()}` | {DESCRIPTIONS[key]} |')
    lines += [
        '',
        'Nextflow options use one dash: `-profile local`, `-profile berzelius`, and `-resume SESSION_ID`.',
        'There is no workflow `--help` page or test profile. See [usage](../usage.md) for complete commands.',
        'See [resources](resources.md) for concurrency and [troubleshooting](../how-to/troubleshooting.md) for failures.',
    ]
    save('reference/parameters.md', lines)

    lines = [
        '# Helper script arguments',
        '',
        'This reference is generated from Python `add_argument` calls without importing CellProfiler.',
        'It lists source expressions, not captured runtime help. Run scientific helpers through Nextflow for normal use.',
        '',
        'Nextflow creates the working folders, stages inputs, and publishes outputs for these helpers.',
        'Direct execution requires the expected task layout and active dependencies.',
        '',
        'The workflow entry point is `nextflow run .`. See [usage](../usage.md).',
        '',
    ]
    for name in ['make_samplesheet', 'prepare', 'run_task', 'merge_features']:
        path = ROOT / 'bin' / f'{name}.py'
        tree = ast.parse(path.read_text())
        lines += [
            f'## {name}.py',
            '',
            {
                'make_samplesheet': 'Writes a samplesheet for a folder of plate folders. Run it by hand before a run.',
                'prepare': 'PREPARE validates images and adapts pipelines.',
                'run_task': 'Runs illumination, segmentation (RunCellpose) or analysis, then validates its outputs.',
                'merge_features': 'The `plate` subcommand merges the batches of one plate into `<plate>.parquet`.',
            }[name],
            '',
            '| Parser in source | Argument | Required, default, choices, or type |',
            '|---|---|---|',
        ]
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'add_argument':
                args = ', '.join(ast.literal_eval(a) for a in node.args)
                options = ', '.join(f'{k.arg}={ast.unparse(k.value)}' for k in node.keywords if k.arg != 'help') or 'Positional argument'
                lines.append(f'| `{ast.unparse(node.func.value)}` | `{args}` | `{options}` |')
        if name == 'merge_features':
            lines += [
                '',
                '`plate` defines the MERGE arguments.',
            ]
        lines += ['']
    lines += [
        '`cp_inputs.py` is a library: the samplesheet and pipeline checks that the scripts above use.',
        '',
        'Argument parsing errors return status 2. Successful helpers return status 0.',
        'Uncaught validation errors return a nonzero status. Nextflow treats them as task failures.',
    ]
    save('reference/cli.md', lines)

    lines = [
        '# CellProfiler pipelines',
        '',
        'This list is generated from the supplied `.cppipe` files in source order.',
        'Both pipelines require CellProfiler and cellprofiler-core 4.2.8.1.',
        '',
        'PREPARE replaces the four input modules with LoadData in working copies.',
        'It adds SaveLabelMasks before spreadsheet export and redirects outputs into each task.',
        'It preserves segmentation and measurement settings. The source files stay unchanged.',
        '',
        'LoadData manifests contain `Metadata_*`, `FileName_<channel>`, and `PathName_<channel>` fields.',
        'Analysis adds `FileName_Illum<channel>` and `PathName_Illum<channel>` fields.',
        'See [file formats](file-formats.md) and [outputs](../output.md).',
        '',
    ]
    lines += [
        '`cp-configs-cellpose/` is the same configuration with Cellpose-SAM for the nuclei.',
        'Its `1_illumination.cppipe` is a link to `cp-configs/1_illumination.cppipe`.',
        'Its `2_analysis.cppipe` has RunCellpose in place of IdentifyPrimaryObjects (module 8). The other modules are the same.',
        '',
    ]
    for path in sorted((ROOT / 'cp-configs').glob('*.cppipe')) + [ROOT / 'cp-configs-cellpose/2_analysis.cppipe']:
        title = path.name if path.parent.name == 'cp-configs' else f'{path.parent.name}/{path.name}'
        lines += [f'## {title}', '', '| Module number | Module |', '|---|---|']
        for module, number in re.findall(r'^(\w+):\[module_num:(\d+)\|', path.read_text(), re.M):
            lines.append(f'| {number} | {module} |')
        lines += ['']
    save('reference/pipelines.md', lines)
    pipe = (ROOT / 'cp-configs/1_illumination.cppipe').read_text()
    regex = re.findall(r'^\s*Regular expression to extract from file name:(.*)', pipe, re.M)[0]
    save(
        'reference/file-formats.md',
        [
            '# Input file formats',
            '',
            'Use this reference to check image names and channel assignments.',
            '',
            'The filename expression below comes directly from the illumination pipeline.',
            '`bin/make_samplesheet.py` uses it to read the metadata from file names. The workflow itself does not.',
            'PREPARE requires the same channel rules in both pipelines.',
            '',
            '```text',
            regex,
            '```',
            '',
            '| Filename channel | CellProfiler image name |',
            '|---|---|',
            '| 405 | DNA |',
            '| 488 | RNA |',
            '| 561 | AGP |',
            '| 638 | Mito |',
            '| 730 | ER |',
            '',
            'Images must be unsigned 8-bit or 16-bit grayscale TIFFs with one series and one page.',
            'The image axes must be YX. Every image within a plate must have the same dimensions.',
            'For `bin/make_samplesheet.py`, the plate name is the parent folder, after resolving file links.',
            '',
            '## Samplesheet',
            '',
            'The samplesheet (`--input`) gives the metadata and the path of each image file.',
            'The files can have any names and be in any folder.',
            'The samplesheet is a CSV file with one row per image file:',
            '',
            '```text',
            'plate,well,site,channel,path',
            'plate1,A02,1,DNA,/data/plate1/A02_s1_w1.tiff',
            'plate1,A02,1,RNA,/data/plate1/A02_s1_w2.tiff',
            '```',
            '',
            '| Column | Required | Meaning |',
            '|---|---|---|',
            '| `plate` | Yes | Plate name. It must start with a letter or digit. Other characters may be letters, digits, dots, underscores, or hyphens. |',
            '| `well` | Yes | Well, for example `A02`. |',
            '| `site` | Yes | Site (field of view) in the well, for example `1`. |',
            '| `channel` | Yes | CellProfiler image name from the pipelines, for example `DNA`. See the table above. |',
            '| `path` | Yes | The TIFF file. A relative path starts from the folder of the samplesheet. |',
            '| `acquisition` | No | Name of the image set in mask file names and `Metadata_Acquisition`. Default: `<well>_s<site>`. |',
            '| any other | No | More metadata. A column `x` becomes `Metadata_X` in the per-cell table. |',
            '',
            'The rows with the same plate, well, site, and other metadata form one image set.',
            'Each image set needs exactly one file for each channel of the pipelines.',
            'Do not use the columns `batch`, `plateImageNumber`, `imageNumber`, and `objectNumber`. The workflow writes them itself.',
            'PREPARE checks every row and every file before the first CellProfiler task starts.',
            '',
            'Each run writes its samplesheet to `logs/run_inputs/samplesheet.csv`.',
            'To make a samplesheet from a folder of images, use `bin/make_samplesheet.py` (see [helper scripts](cli.md)).',
            'Check the result, delete rows that you do not want, then give it with `--input`.',
            '',
            '## Manifests',
            '',
            'Generated manifests use one CSV row per image set, with metadata and a path/filename pair for each channel.',
            'The workflow creates these manifests from the samplesheet or the image folder.',
            '',
            'Metadata includes Plate, Well, Site, the other filename or samplesheet fields (for these images: Row, Column, X, Y), Acquisition, and Batch.',
            'See [input layout](../usage.md) and [output formats](../output.md).',
        ],
    )


def on_pre_build(config):
    generate()


if __name__ == '__main__':
    generate()
