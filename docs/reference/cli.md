# Helper script arguments

This reference is generated from Python `add_argument` calls without importing CellProfiler.
It lists source expressions, not captured runtime help. Run scientific helpers through Nextflow for normal use.

Nextflow creates the working folders, stages inputs, and publishes outputs for these helpers.
Direct execution requires the expected task layout and active dependencies.

The workflow entry point is `nextflow run .`. See [usage](../usage.md).

## prepare.py

PREPARE validates images and adapts pipelines.

| Parser in source | Argument | Required, default, choices, or type |
|---|---|---|
| `parser` | `--configs` | `type=Path, required=True` |
| `parser` | `--batch-size` | `type=int, required=True` |
| `parser` | `--images-list` | `type=Path` |
| `parser` | `--out` | `type=Path, default=Path('prepared')` |

## run_task.py

Runs illumination or analysis, then validates its outputs.

| Parser in source | Argument | Required, default, choices, or type |
|---|---|---|
| `parser` | `kind` | `choices=['illumination', 'analysis']` |
| `parser` | `--plate` | `required=True` |
| `parser` | `--batch` | `default='illumination'` |
| `parser` | `--manifest` | `type=Path, required=True` |
| `parser` | `--pipeline` | `type=Path, required=True` |
| `parser` | `--contract` | `type=Path, required=True` |
| `parser` | `--plugins` | `type=Path, default=Path('plugins')` |
| `parser` | `--illumination` | `type=Path` |

## merge_features.py

Use the `plate` subcommand to merge batches, or `all` to concatenate plate tables.

| Parser in source | Argument | Required, default, choices, or type |
|---|---|---|
| `one` | `--plate` | `required=True` |
| `one` | `--manifest` | `type=Path, required=True` |
| `one` | `--batches` | `type=Path, required=True` |
| `one` | `--contract` | `type=Path, required=True` |
| `every` | `tables` | `type=Path, nargs='+'` |
| `command` | `--out` | `type=Path, required=True` |
| `command` | `--report` | `type=Path, required=True` |

`one` defines `plate` arguments. `every` defines `all` arguments.
`command` adds `--out` and `--report` to both subcommands.

## convert_watershed.py

A one-time conversion utility. The workflow does not call it.

| Parser in source | Argument | Required, default, choices, or type |
|---|---|---|
| `parser` | `source` | `Positional argument` |
| `parser` | `destination` | `Positional argument` |

`cp_inputs.py` is an imported validation module, not a command-line interface.

Argument parsing errors return status 2. Successful helpers return status 0.
Uncaught validation errors return a nonzero status. Nextflow treats them as task failures.
