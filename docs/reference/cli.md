# Helper script arguments

This reference is generated from Python `add_argument` calls without importing CellProfiler.
It lists source expressions, not captured runtime help. Run scientific helpers through Nextflow for normal use.

Nextflow creates the working folders, stages inputs, and publishes outputs for these helpers.
Direct execution requires the expected task layout and active dependencies.

The workflow entry point is `nextflow run .`. See [usage](../usage.md).

## make_samplesheet.py

Writes a samplesheet for a folder of plate folders. Run it by hand before a run.

| Parser in source | Argument | Required, default, choices, or type |
|---|---|---|
| `parser` | `--images` | `type=Path, required=True` |
| `parser` | `--configs` | `type=Path, required=True` |
| `parser` | `--out` | `type=Path, required=True` |

## prepare.py

PREPARE validates images and adapts pipelines.

| Parser in source | Argument | Required, default, choices, or type |
|---|---|---|
| `parser` | `--configs` | `type=Path, required=True` |
| `parser` | `--samplesheet` | `type=Path, required=True` |
| `parser` | `--batch-size` | `type=int, required=True` |
| `parser` | `--out` | `type=Path, default=Path('prepared')` |

## run_task.py

Runs illumination, segmentation (RunCellpose) or analysis, then validates its outputs.

| Parser in source | Argument | Required, default, choices, or type |
|---|---|---|
| `parser` | `kind` | `choices=['illumination', 'segmentation', 'analysis']` |
| `parser` | `--plate` | `required=True` |
| `parser` | `--batch` | `default='illumination'` |
| `parser` | `--manifest` | `type=Path, nargs='+', required=True` |
| `parser` | `--pipeline` | `type=Path, required=True` |
| `parser` | `--contract` | `type=Path, required=True` |
| `parser` | `--plugins` | `type=Path, default=Path('plugins')` |
| `parser` | `--illumination` | `type=Path` |
| `parser` | `--segmentation` | `type=Path` |
| `parser` | `--device` | `choices=['cpu', 'gpu'], default='cpu'` |
| `parser` | `--workers` | `type=int, default=1` |
| `parser` | `--cpus` | `type=int, default=1` |

## merge_features.py

The `plate` subcommand merges the batches of one plate into `<plate>.parquet`.

| Parser in source | Argument | Required, default, choices, or type |
|---|---|---|
| `plate` | `--plate` | `required=True` |
| `plate` | `--manifest` | `type=Path, required=True` |
| `plate` | `--batches` | `type=Path, required=True` |
| `plate` | `--contract` | `type=Path, required=True` |
| `plate` | `--out` | `type=Path, required=True` |
| `plate` | `--report` | `type=Path, required=True` |

`plate` defines the MERGE arguments.

`cp_inputs.py` is a library: the samplesheet and pipeline checks that the scripts above use.

Argument parsing errors return status 2. Successful helpers return status 0.
Uncaught validation errors return a nonzero status. Nextflow treats them as task failures.
