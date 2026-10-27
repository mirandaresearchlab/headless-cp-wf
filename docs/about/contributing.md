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
Run every check by hand with `uvx pre-commit run --all-files`.

## Check software changes

In the full `cp-headless` environment, run:

```bash
python -m pytest -q tests
```

Expected result: all tests pass. The full suite requires CellProfiler and Java.
The input, output, and merge tests can also run with their smaller NumPy/tifffile/pytest dependencies.
Keep documentation changes with the behavior changes they describe.
See [pre-commit checks](#pre-commit-checks) to run the full suite automatically before each commit.

For batch-equivalence checks, `tests/benchmark.nf` reuses a completed baseline's illumination files.
`tests/compare_runs.py` compares masks and gzip feature tables, excluding batch-dependent fields.
Review their help and source before use. These benchmark runs were not executed during this documentation update.

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

These runs found two problems. Both are fixed and checked again.
Projects that started from the repository folder shared one session and one results folder.
The check for free disk space was skipped when `nscquota` gave no answer. The script now tries three times.
This workspace did not provide Nextflow, Conda, or CellProfiler.
Historical runtime and disk figures are labelled in [resource planning](../reference/resources.md).
Scientific claims require representative image review beyond these software checks.
