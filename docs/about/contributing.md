# Contributing

This guide is for people who change the code of cp-headless. Read the [home page](../index.md) first.

## Code layout

```text
.
├── main.nf                  the Nextflow workflow: processes, checks and the order of the steps
├── nextflow.config          parameters, resources, profiles and run reports
├── nextflow_schema.json     description of each parameter (source of the parameter reference page)
├── conf/
│   ├── slurm.config         settings for -profile slurm
│   └── berzelius.config     settings for -profile berzelius (loaded after slurm.config)
├── bin/                     Python helper scripts. Nextflow adds this folder to the PATH of each job.
│   ├── patch_cppipe.py      prepares the CellProfiler pipeline
│   ├── check_chunk.py       checks the result of one CellProfiler job and makes its mask list
│   └── merge_features.py    merges the tables of all chunks
├── scripts/
│   ├── berzelius/           helper scripts for Berzelius (see the Berzelius guide)
│   ├── bootstrap.sh         makes the development environment and installs the Git hook
│   ├── check-comment-spacing.py  checks the comment layout of the code files
│   ├── docker-entrypoint.sh starts the workflow in the all-in-one Docker image
│   ├── start-docker-in-container.sh  starts Docker inside a lab workstation container
│   ├── test-helpers-py38.sh runs the helper tests on Python 3.8
│   └── test-nextflow.sh     runs the workflow on the test data without CellProfiler
├── tests/
│   ├── images/              6 small test images (2 plates, 3 sites, 1 channel)
│   ├── test.cppipe          the test pipeline
│   ├── test_helpers.py      tests of the helper scripts in bin/
│   ├── test_workflow.py     tests of main.nf without CellProfiler (grouping, parameters, Slurm, Berzelius)
│   ├── test_berzelius_scripts.py  tests of scripts/berzelius/
│   ├── test_comment_spacing.py    tests of the comment layout check
│   ├── test_schema.py       tests that nextflow_schema.json agrees with nextflow.config
│   ├── test_cellprofiler.py tests with real CellProfiler in Docker
│   ├── test_local_cellprofiler.py  the same end-to-end test without a container (-profile local)
│   ├── reference/           per-object features of the test data (made in the official container)
│   └── cp_make_pipeline.py  makes test pipelines in the CellProfiler container
├── docs/                    this documentation site (MkDocs). docs/.hooks/ makes the reference pages.
├── mkdocs.yml               settings and menu of the documentation site
├── requirements-docs.txt    the exact versions of the documentation tools
├── Dockerfile               the all-in-one image: Nextflow, Java and CellProfiler
├── .github/workflows/ci.yml the automatic checks on GitHub
├── .github/workflows/docs.yml  builds the documentation site and publishes it on GitHub Pages
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

The tests have five levels. The fast tests run on each commit.

| Command | What it tests | Time |
| --- | --- | --- |
| `uv run pytest` | The helper scripts and the Berzelius scripts | seconds |
| `bash scripts/test-helpers-py38.sh` | The same tests, with the helpers on Python 3.8 | seconds |
| `uv run pytest -m workflow` | `main.nf` without CellProfiler (`-stub-run`): grouping, checks, parameters, profiles, errors, new tries, `-resume`, Slurm and Berzelius job scripts | about 1 minute. Pre-commit skips it in CI. The `workflow` job runs it. |
| `uv run pytest -m cellprofiler` | Real CellProfiler in Docker: the pipeline preparation, and a complete run of the test data | some minutes |
| `uv run pytest -m local_cellprofiler` | Real CellProfiler without a container: a complete run of the test data with `-profile test,local`. Needs `cellprofiler` 4.2.8 on PATH ([Run without Docker](../how-to/run-without-docker.md)), otherwise skipped. | some minutes |

Other commands:

```bash
uv run ruff check bin tests
uv run ruff format --check bin tests
bash scripts/test-nextflow.sh          # the test profile without CellProfiler
nextflow lint main.nf nextflow.config conf/*.config
uv run pre-commit run --all-files      # all automatic checks
```

**Reference results.** The end-to-end tests run the `test` profile with real CellProfiler, in Docker
(`test_cellprofiler.py`) and without a container (`test_local_cellprofiler.py`). Both compare the number of
nuclei in each image with the numbers from the first version of the workflow. Both also compare every
feature value of the Nuclei and Cells tables with `tests/reference/`, within a relative difference of 1e-4
(`FEATURE_RTOL`). A different number means a change in the biological results. Do not change the reference
without a clear reason (see `tests/reference/README.md`).

**Tests without a cluster.** The Slurm and Berzelius tests use a fake `sbatch` program. The fake program
saves the job script that Nextflow makes and then refuses the job. A fake `apptainer` program makes an empty
image file. Thus the tests can check the `#SBATCH` lines and the use of `/scratch/local` on any computer.

**Write a test first.** When you change behaviour, first write a test that fails. Then change the code.

## Automatic checks on GitHub

`.github/workflows/ci.yml` has five jobs. All run on each push to each branch.

1. **pre-commit** runs all checks of `.pre-commit-config.yaml`. If Ruff or another check corrects files,
   the job runs the checks again (3 times or fewer). Then it commits the corrections as
   `github-actions[bot]` and pushes them to the same branch. The job fails in these cases:
   - A check fails and no check can correct the problem.
   - The checks still fail after the corrections.
   - GitHub cannot push the correction.
2. **workflow** runs the fast tests and `pytest -m workflow` on Ubuntu and on macOS. macOS is for
   development only: the job checks the workflow logic, not CellProfiler.
3. **cellprofiler** runs `pytest -m cellprofiler` with real CellProfiler in Docker on the Ubuntu runner.
4. **workstation-local** is a lab workstation without Docker: `root` in an Ubuntu 24.04 container. It
   installs micromamba and the two conda environments of [Run without Docker](../how-to/run-without-docker.md),
   then runs `pytest -m local_cellprofiler`.
5. **workstation-docker** is a lab workstation with Docker inside: a privileged Ubuntu 24.04 container with a
   volume on `/var/lib/docker`. It starts Docker with `scripts/start-docker-in-container.sh`, then runs
   `pytest -m cellprofiler`.

GitHub cannot run Berzelius. The tests run the Berzelius scripts and job settings with fake `sbatch`, `squeue`
and `apptainer` programs. Only a run on Berzelius proves that they work there. The guides record which
commands ran on Berzelius.

The pre-commit job needs `contents: write` permission for the bot commit. On a protected branch, GitHub
Actions must have permission to push. Otherwise the push fails, and you must run the checks yourself:

```bash
uv run pre-commit run --all-files
git add --update
git commit -m "style: apply pre-commit corrections"
git push
```

## Documentation

The documentation site uses [MkDocs](https://www.mkdocs.org/) and the
[Material](https://squidfunk.github.io/mkdocs-material/) theme. Its pages are in `docs/`, and its menu is in
`mkdocs.yml`. The pages follow four types:

| Folder | Type | Content |
| --- | --- | --- |
| `tutorials/` | Tutorial | One guided run on the test data |
| `how-to/` | How-to guide | Steps for one task |
| `reference/` | Reference | Parameters, scripts, file formats: complete, for looking up |
| `explanation/` | Explanation | How and why the workflow works as it does |

The build makes some reference pages from the code. Do not edit them by hand:

| Page | Made from |
| --- | --- |
| `reference/parameters.md` | `nextflow_schema.json` |
| `reference/cli.md` | the `--help` text of the scripts in `bin/` |
| `reference/api.md` | the numpy docstrings of the scripts in `bin/` |
| `about/changelog.md` | `CHANGELOG.md` |

When you add or change a parameter, change `nextflow.config` and `nextflow_schema.json` together.
`tests/test_schema.py` fails if they disagree. A change to behaviour, a parameter or an output changes the
documentation in the same commit.

See the site on your computer while you edit it (at http://127.0.0.1:8000):

```bash
uv run --with-requirements requirements-docs.txt mkdocs serve
```

Check the site as the automatic check does. `--strict` stops on broken links and missing pages:

```bash
uv run --with-requirements requirements-docs.txt mkdocs build --strict
```

**Publishing.** `.github/workflows/docs.yml` builds the site for each pull request. For each push to `main`,
it also publishes the site on GitHub Pages, at https://mirandaresearchlab.github.io/headless-cp-wf/. Once,
an owner of the repository must turn this on: **Settings → Pages → Build and deployment → Source:
GitHub Actions**.

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
