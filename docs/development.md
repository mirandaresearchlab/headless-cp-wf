# Development guide

This guide is for people who change the code of cp-headless. Read the [README](../README.md) first.

## Code layout

```text
.
├── main.nf                  the Nextflow workflow: processes, checks and the order of the steps
├── nextflow.config          parameters, resources, profiles and run reports
├── conf/
│   ├── slurm.config         settings for -profile slurm
│   └── berzelius.config     settings for -profile berzelius (loaded after slurm.config)
├── bin/                     Python helper scripts. Nextflow adds this folder to the PATH of each job.
│   ├── patch_cppipe.py      prepares the CellProfiler pipeline
│   ├── check_chunk.py       checks the result of one CellProfiler job and makes its mask list
│   └── merge_features.py    merges the tables of all chunks
├── scripts/
│   ├── berzelius/           helper scripts for Berzelius (see docs/berzelius.md)
│   ├── bootstrap.sh         makes the development environment and installs the Git hook
│   ├── check-comment-spacing.py  checks the comment layout of the code files
│   ├── docker-entrypoint.sh starts the workflow in the all-in-one Docker image
│   ├── test-helpers-py38.sh runs the helper tests on Python 3.8
│   └── test-nextflow.sh     runs the workflow on the test data without CellProfiler
├── tests/
│   ├── images/              6 small test images (2 plates, 3 sites, 1 channel)
│   ├── test.cppipe          the test pipeline
│   ├── test_helpers.py      tests of the helper scripts in bin/
│   ├── test_workflow.py     tests of main.nf without CellProfiler (grouping, parameters, Slurm, Berzelius)
│   ├── test_berzelius_scripts.py  tests of scripts/berzelius/
│   ├── test_comment_spacing.py    tests of the comment layout check
│   ├── test_cellprofiler.py tests with real CellProfiler in Docker
│   └── cp_make_pipeline.py  makes test pipelines in the CellProfiler container
├── Dockerfile               the all-in-one image: Nextflow, Java and CellProfiler
├── .github/workflows/ci.yml the automatic checks on GitHub
├── pyproject.toml           settings of the Python development tools
└── uv.lock                  the exact versions of the Python development tools
```

The workflow keeps temporary job files in `work/` and copies the final results to `--outdir`.

## Important rule: Python 3.8 in `bin/`

The scripts in `bin/` run in the CellProfiler 4.2.8 container. That container has **Python 3.8**. Do not use
Python features that are newer than 3.8 in `bin/`, for example `str.removeprefix`. Ruff checks `bin/` for
Python 3.8. `scripts/test-helpers-py38.sh` runs the helper tests on Python 3.8.

The helper scripts use only the standard library of Python. Thus they need no extra packages in the
container.

## Comments in the code

Comments explain what a part of the code does and why. A reader of the raw code must understand the
steps without other documents. These rules apply to all code files:

- Put an empty line above the first line of each comment block.
- Keep the lines of one block together, without empty lines between them.
- You can put a comment at the end of a code line anywhere.
- In Python, put a comment for a `for`, `if`, `with` or `try` block above that line, not as the first line
  inside the block. Ruff removes an empty line at the start of such a block.
- Give each Python module and function a docstring in
  [numpy style](https://numpydoc.readthedocs.io/en/latest/format.html). Start with a summary line and,
  if needed, an explanation. Then add the sections `Parameters`, `Returns` and `Raises` where they apply.
  Write each parameter as `name : type`, with its meaning on the next line.

Ruff checks the docstrings (rules `D`, numpy convention). It does not check that each parameter is
in the `Parameters` section, so check that yourself.
`scripts/check-comment-spacing.py` checks the empty lines. It runs before each commit. Run it by hand
with `uv run python scripts/check-comment-spacing.py`. The script ignores lines that only look like
comments: `#!` first lines, `#SBATCH` lines and the `# syntax=` line of the Dockerfile.

## Prepare the development environment

You need [uv](https://docs.astral.sh/uv/). The development tools are Ruff, pytest and pre-commit. uv does not
install CellProfiler, because the container supplies it. Nextflow, Java and Docker are system programs, so
uv does not manage them either.

```bash
# Once: make .venv, install the exact tool versions, and install the Git hook.
./scripts/bootstrap.sh
source .venv/bin/activate

# Later: install the exact versions again.
uv sync --locked --all-groups
```

`bootstrap.sh` does the same as these commands:

```bash
uv venv --python 3.12 --prompt cp-headless
uv sync --all-groups
uv run pre-commit install
```

## Tests

The tests have four levels. The fast tests run on each commit.

| Command | What it tests | Time |
| --- | --- | --- |
| `uv run pytest` | The helper scripts and the Berzelius scripts | seconds |
| `bash scripts/test-helpers-py38.sh` | The same tests, with the helpers on Python 3.8 | seconds |
| `uv run pytest -m workflow` | `main.nf` without CellProfiler (`-stub-run`): grouping, checks, parameters, Slurm and Berzelius job scripts | about 1 minute |
| `uv run pytest -m cellprofiler` | Real CellProfiler in Docker: the pipeline preparation, and a complete run of the test data | some minutes |

Other commands:

```bash
uv run ruff check bin tests
uv run ruff format --check bin tests
bash scripts/test-nextflow.sh          # the test profile without CellProfiler
nextflow lint main.nf nextflow.config conf/*.config
uv run pre-commit run --all-files      # all automatic checks
```

**Reference results.** `tests/test_cellprofiler.py` runs the `test` profile with real CellProfiler. It
compares the number of nuclei in each image with the numbers from the first version of the workflow. A
different number means a change in the biological results. Do not change the reference numbers without a
clear reason.

**Tests without a cluster.** The Slurm and Berzelius tests use a fake `sbatch` program. The fake program
saves the job script that Nextflow makes and then refuses the job. A fake `apptainer` program makes an empty
image file. Thus the tests can check the `#SBATCH` lines and the use of `/scratch/local` on any computer.

**Write a test first.** When you change behaviour, first write a test that fails. Then change the code.

## Automatic checks on GitHub

`.github/workflows/ci.yml` has two jobs. Both run on each push to each branch.

1. **pre-commit** runs all checks of `.pre-commit-config.yaml`. If Ruff or another check corrects files,
   the job runs the checks again (3 times or fewer). Then it commits the corrections as
   `github-actions[bot]` and pushes them to the same branch. The job fails in these cases:
   - A check fails and no check can correct the problem.
   - The checks still fail after the corrections.
   - GitHub cannot push the correction.
2. **cellprofiler** runs `pytest -m cellprofiler` with real CellProfiler in Docker.

The pre-commit job needs `contents: write` permission for the bot commit. On a protected branch, GitHub
Actions must have permission to push. Otherwise the push fails, and you must run the checks yourself:

```bash
uv run pre-commit run --all-files
git add --update
git commit -m "style: apply pre-commit corrections"
git push
```

## Update the CellProfiler version

1. Find the new image and its digest:
   `docker pull cellprofiler/cellprofiler:<tag>` and
   `docker inspect --format '{{index .RepoDigests 0}}' cellprofiler/cellprofiler:<tag>`.
2. Change `container` in `nextflow.config` and the `CELLPROFILER_*` arguments in the `Dockerfile`.
3. Find the Python version in the new image. Change the Python version for `bin/` in `pyproject.toml` and in
   `scripts/test-helpers-py38.sh`.
4. Run all tests. If the reference numbers in `tests/test_cellprofiler.py` change, find the cause before you
   change the numbers.
5. Write the change in `CHANGELOG.md`.
