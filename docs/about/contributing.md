# Build and maintain the documentation

Use this page to preview the site and keep it consistent with the code.

## Preview the site

Run from the repository root with Python 3.12 available:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-docs.txt
.venv/bin/python -m mkdocs serve
```

Expected result: MkDocs serves the guide at `http://127.0.0.1:8000`.
Stop the server with Ctrl-C. Documentation dependencies are separate from the CellProfiler environment.

For a strict build:

```bash
.venv/bin/python -m mkdocs build --strict
```

Expected result: the static site appears in `site/` with no warnings or broken internal links.
The build hook regenerates parameter defaults from configuration files,
CLI arguments from Python syntax, and pipeline module lists from the `.cppipe` files.
It does not import CellProfiler or run scientific jobs.
Edit explanations in the generator and source settings in their original files.
Do not edit generated reference pages directly.

Mermaid diagrams use [Material's supported configuration](https://squidfunk.github.io/mkdocs-material/reference/diagrams/).
The browser renders them from text. A strict build checks Markdown and links, but does not execute Mermaid in a browser.

## Continuous checks and optional hosting

The `docs` GitHub Actions workflow builds documentation on pushes and pull requests.
Each push to the default branch also publishes the site to
[GitHub Pages](https://mirandaresearchlab.github.io/headless-cp-wf/).
Pull requests build the site but never publish it.
Hosting requires GitHub Actions as the source in the repository's Pages settings.

The `tests` workflow runs on the same events. It runs the input, output and merge tests
with NumPy, tifffile and pytest only. The CellProfiler plugin tests do not run on GitHub.

## Pre-commit checks

The CellProfiler plugin tests run locally before each commit. Install the hooks once:

```bash
conda env create -f environment.yml
uvx pre-commit install
```

When a Python file, pipeline or `environment.yml` changes, the hook runs the full suite in
the `cp-headless` environment through `scripts/test-cellprofiler.sh`. It works with conda, mamba
or micromamba. Set `CP_ENV` to use another environment name or a prefix path.
A second hook runs the strict documentation build when documentation sources change.
Ruff fixes and formats changed Python files, then reports the errors it cannot fix. Its settings are in `ruff.toml`.
`nextflow lint -format` formats the workflow, the modules and the configuration files, then reports errors.
It needs `nextflow` on `PATH`, for example in the activated `cp-headless` environment.
If a hook changes files, the commit stops. Check the changes, add them with `git add`, and commit again.
Run every check by hand with `uvx pre-commit run --all-files`.

## Code layout

The workflow follows the nf-core layout:

| Path | Content |
|---|---|
| `main.nf` | Entry point: checks the parameters, chooses the output folder, starts the workflow |
| `workflows/cellprofiler.nf` | The workflow: how the samplesheet, plates and batches flow through the steps |
| `modules/local/<step>/main.nf` | One process each: PREPARE, ILLUMINATION, ANALYSIS, MERGE, CONCAT |
| `nextflow.config` | All parameters, reports and profiles |
| `conf/base.config` | Process settings for every profile |
| `conf/local.config`, `conf/berzelius.config` | Executor settings for one profile |
| `bin/` | Python scripts that the processes run. `cp_inputs.py` is the shared input library |
| `plugins/` | The SaveLabelMasks CellProfiler module |
| `scripts/` | Berzelius run scripts and the Parquet conversion |
| `tests/` | Unit tests and `make_fixture.py` |

Python functions use NumPy-style docstrings. The processes stage `bin/` and `plugins/` as inputs,
so a change to a script reruns the tasks that use it on `-resume`.

## Check software changes

In the full `cp-headless` environment, run:

```bash
python -m pytest -q tests
```

Expected result: all tests pass. The full suite requires CellProfiler and Java.
The input, output, and merge tests can also run with their smaller NumPy/tifffile/pytest dependencies.
Keep documentation changes with the behavior changes they describe.
See [pre-commit checks](#pre-commit-checks) to run the full suite automatically before each commit.

The Parquet tests need DuckDB, which `cp-headless` does not have. Without it, pytest skips them. Run them with:

```bash
uv run --python 3.12 --with duckdb==1.4.1 --with pytest pytest -q tests/test_concat_parquet.py
```

## Validation status

The documentation was checked against `main.nf`, both profiles, Python helpers, pipelines, and saved work artifacts.
The strict MkDocs build passed. All 26 input, output, and merge unit tests passed.
Those tests used Python 3.9.25, NumPy 1.24.4, tifffile 2022.4.8, and pytest 7.4.4.
This smaller test environment is not the complete pinned CellProfiler environment.
The documentation skill checker reported zero errors and three configuration warnings.
Two concern the unknown hosting URLs. The third concerns the absent Nextflow schema.
Parameter documentation instead reads defaults directly from the configuration files.
The real-image fixture command was run in a temporary folder.
The table-reading example was checked against a saved plate table.

A complete Nextflow run, a fresh Conda install, and Slurm execution were not performed.
On Berzelius, the conda setup in [Run on Berzelius](../how-to/run-on-hpc.md) was done.
A test with `scripts/berzelius-interactive.sh` on 18 cores ran all 62 tasks on 3 plates (54 image sets).
It took 22 minutes and 5.1 core-hours.

The three Berzelius scripts then ran on a small input: 3 plates with 2 cropped image sets each.
Each run had 14 tasks and ended with `[SUCCESS] completed=14 failed=0`.
Each run wrote 98 table rows to its own results folder.

- `scripts/berzelius-run.sbatch` (Slurm head job): completed in 5 minutes 47 seconds.
- `scripts/berzelius-interactive.sh` (6-core Slurm allocation): completed in 1 minute 39 seconds.
- `scripts/berzelius-run-plates.sbatch` (one plate at a time): completed in 15 minutes 40 seconds.
  It ran 3 plates, wrote the `DONE` files and deleted the work folders.

A run with three plates of 17,100 images each stopped on plate 3 because two tasks reached a time limit of 2 hours.
The failure text in [When a job stops or fails](../how-to/berzelius-faq.md#when-a-job-stops-or-fails) comes from that run.
The restart of that run, and a `scancel` of the head job, were not tested when the FAQ was written.

The small runs found two problems. Both are fixed and checked again.
Projects that started from the repository folder shared one session and one results folder.
The check for free disk space was skipped when `nscquota` gave no answer. The script now tries three times.
This workspace did not provide Nextflow, Conda, or CellProfiler.
Historical runtime and disk figures are labelled in [resource planning](../reference/resources.md).
Scientific claims require representative image review beyond these software checks.
