"""Generate reference pages from repository source without importing workflow dependencies."""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESCRIPTIONS = {
    'images': 'Required image root containing one folder per plate.',
    'configs': 'Required folder containing the two named pipeline files.',
    'project': 'Output project name. Defaults to the session ID. Existing names owned by another session fall back to that ID.',
    'outdir': 'Parent of projects/. Must keep the resolved output outside the image root.',
    'batch_size': 'Positive number of complete image sets per analysis task.',
    'task_cpus': 'CPU request for each task. Library threads remain limited to one.',
    'task_memory': 'Memory request for each task. Must be positive and no larger than total_memory, on either profile.',
    'task_time': 'Time limit for each task.',
    'total_cpus': 'Positive shared CPU budget for the local executor.',
    'total_memory': 'Shared memory budget for local execution. Also bounds task_memory during validation on both profiles.',
    'max_forks': 'Local per-process concurrency limit. Zero adds no limit beyond executor resources.',
    'max_jobs': 'Maximum submitted/active tasks managed by the Slurm executor.',
    'nf_work_dir': 'Work directory override. Local fallback: launchDir/work. Berzelius fallback: shared_dir/nextflow-work.',
    'conda_cache': 'Conda cache path. Local fallback: launchDir/.nextflow/conda. Berzelius fallback: shared_dir/conda-cache. No tasks currently declare a Conda environment.',
    'shared_dir': 'Berzelius root for default work and Conda cache paths. Supply it or both explicit paths.',
    'slurm_partition': 'Slurm partition. Confirm access and the partition name with your cluster.',
    'slurm_account': 'Optional Slurm allocation account passed with --account.',
    'max_retries': 'Retry limit for task exit statuses 137 or 143. Resources do not increase on retry.',
}


def params(path):
    text = path.read_text()
    block = re.search(r'^params\s*\{(.*?)^\}', text, re.M | re.S)
    if not block:
        raise ValueError(f'No params block in {path}')
    return dict(re.findall(r'^\s*(\w+)\s*=\s*([^\n]+)', block.group(1), re.M))


def save(name, lines):
    path = ROOT / 'docs' / name
    content = '\n'.join(lines) + '\n'
    if not path.exists() or path.read_text() != content:
        path.write_text(content)


def generate():
    base = params(ROOT / 'nextflow.config')
    local = {**base, **params(ROOT / 'nf-config/local.config')}
    cluster = {**base, **params(ROOT / 'nf-config/berzelius.config')}
    if set(base) != set(DESCRIPTIONS):
        raise ValueError('Update documentation descriptions to match nextflow.config parameters')
    lines = ['# Workflow parameters', '',
             'This reference is generated from `nextflow.config` and both profile files on every documentation build.', '',
             'Use `--name value` for these parameters. `null` means no explicit value.',
             'Defaults below are configuration values. Descriptions explain path fallbacks and scope.', '',
             '| Parameter | Local default | Berzelius default | Meaning |', '|---|---|---|---|']
    for key in base:
        lines.append(f'| `--{key}` | `{local[key].strip()}` | `{cluster[key].strip()}` | {DESCRIPTIONS[key]} |')
    lines += ['', 'Nextflow options use one dash: `-profile local`, `-profile berzelius`, and `-resume SESSION_ID`.',
              'There is no workflow `--help` page or test profile. See [usage](../usage.md) for complete commands.',
              'See [resources](resources.md) for concurrency and [troubleshooting](../how-to/troubleshooting.md) for failures.']
    save('reference/parameters.md', lines)

    lines = ['# Helper script arguments', '',
             'This reference is generated from Python `add_argument` calls without importing CellProfiler.',
             'It lists source expressions, not captured runtime help. Run scientific helpers through Nextflow for normal use.', '',
             'Nextflow creates the working folders, stages inputs, and publishes outputs for these helpers.',
             'Direct execution requires the expected task layout and active dependencies.', '',
             'The workflow entry point is `nextflow run .`. See [usage](../usage.md).', '']
    for name in ['prepare', 'run_task', 'merge_features', 'convert_watershed']:
        path = ROOT / 'bin' / f'{name}.py'
        tree = ast.parse(path.read_text())
        lines += [f'## {name}.py', '',
                  {'prepare': 'PREPARE validates images and adapts pipelines.',
                   'run_task': 'Runs illumination or analysis, then validates its outputs.',
                   'merge_features': 'Use the `plate` subcommand to merge batches, or `all` to concatenate plate tables.',
                   'convert_watershed': 'A one-time conversion utility. The workflow does not call it.'}[name], '',
                  '| Parser in source | Argument | Required, default, choices, or type |', '|---|---|---|']
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'add_argument':
                args = ', '.join(ast.literal_eval(a) for a in node.args)
                options = ', '.join(f'{k.arg}={ast.unparse(k.value)}' for k in node.keywords if k.arg != 'help') or 'Positional argument'
                lines.append(f'| `{ast.unparse(node.func.value)}` | `{args}` | `{options}` |')
        if name == 'merge_features':
            lines += ['', '`one` defines `plate` arguments. `every` defines `all` arguments.', '`command` adds `--out` and `--report` to both subcommands.']
        lines += ['']
    lines += ['`cp_inputs.py` is an imported validation module, not a command-line interface.', '',
              'Argument parsing errors return status 2. Successful helpers return status 0.',
              'Uncaught validation errors return a nonzero status. Nextflow treats them as task failures.']
    save('reference/cli.md', lines)

    lines = ['# CellProfiler pipelines', '',
             'This list is generated from the supplied `.cppipe` files in source order.',
             'Both pipelines require CellProfiler and cellprofiler-core 4.2.8.1.', '',
             'PREPARE replaces the four input modules with LoadData in working copies.',
             'It adds SaveLabelMasks before spreadsheet export and redirects outputs into each task.',
             'It preserves segmentation and measurement settings. The source files stay unchanged.', '',
             'LoadData manifests contain `Metadata_*`, `FileName_<channel>`, and `PathName_<channel>` fields.',
             'Analysis adds `FileName_Illum<channel>` and `PathName_Illum<channel>` fields.',
             'See [file formats](file-formats.md) and [outputs](../output.md).', '']
    for path in sorted((ROOT / 'cp-configs').glob('*.cppipe')):
        lines += [f'## {path.name}', '', '| Module number | Module |', '|---|---|']
        for module, number in re.findall(r'^(\w+):\[module_num:(\d+)\|', path.read_text(), re.M):
            lines.append(f'| {number} | {module} |')
        lines += ['']
    save('reference/pipelines.md', lines)
    pipe = (ROOT / 'cp-configs/1_illumination.cppipe').read_text()
    regex = re.findall(r'^\s*Regular expression to extract from file name:(.*)', pipe, re.M)[0]
    save('reference/file-formats.md', ['# Input file formats', '',
        'Use this reference to check image names and channel assignments.', '',
        'The filename expression below comes directly from the illumination pipeline.',
        'PREPARE requires compatible metadata and channel rules in the analysis pipeline.', '',
        '```text', regex, '```', '',
        '| Filename channel | CellProfiler image name |', '|---|---|',
        '| 405 | DNA |', '| 488 | RNA |', '| 561 | AGP |', '| 638 | Mito |', '| 730 | ER |', '',
        'Images must be unsigned 8-bit or 16-bit grayscale TIFFs with one series and one page.',
        'The image axes must be YX. Every image within a plate must have the same dimensions.',
        'Plate identity comes from the parent folder after resolving file links.', '',
        'Generated manifests use one CSV row per image set, with metadata and a path/filename pair for each channel.',
        'The workflow creates these manifests. Users do not supply a separate spreadsheet.', '',
        'Metadata includes Plate, Well, Row, Column, Site, X, Y, Acquisition, and Batch.',
        'See [input layout](../usage.md) and [output formats](../output.md).'])


def on_pre_build(config):
    generate()


if __name__ == '__main__':
    generate()
