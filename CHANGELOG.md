# Changelog

## Unreleased

The CellProfiler measurements did not change. A run of the `test` profile gives the same Image, Nuclei and
Cells values as the original prototype, apart from work-folder paths and execution times.

### Added: Berzelius

- `-profile berzelius` runs the workflow on the Berzelius cluster (NSC). It follows the rules of the site:
  - All jobs go to a CPU partition (`berzelius-cpu` or `berzelius-hopper-cpu`). The workflow stops before it
    submits a job if the account is missing or if the partition is not a CPU partition.
  - Each CellProfiler job asks for 1 core and 7 GB. Each new try adds 1 core and 7 GB.
  - Jobs run on the local disk `/scratch/local`. CellProfiler runs in Apptainer.
  - The queue holds 64 jobs or fewer. No job asks for more than 72 hours.
  - The workflow stops if the work folder, the results or the image cache is in `$HOME`.
- `scripts/berzelius/`: `preflight.sh`, `smoke_test.sh`, `submit.sh`, the head job `run_nextflow.sbatch` and
  `make_env.sh`, which writes the settings file from options. A second `submit.sh` with the same run folder continues the run.
- [Berzelius: set up](https://mirandaresearchlab.github.io/headless-cp-wf/how-to/berzelius-setup/): the Berzelius guide.
- On a cluster, the workflow warns when more than 500 image sets run as one job (`chunk_size 0`).
- CellProfiler jobs ignore your own Python packages (`PYTHONNOUSERSITE=1`).

### Changed: two supported environments

The workflow now supports two environments: a lab workstation (Ubuntu, `root`, for example a container on a
lab server) and Berzelius. Each one has its own guides and tests.

- Lab workstation without Docker: `-profile local` with CellProfiler 4.2.8 from conda (bioconda). See
  [Run without Docker](https://mirandaresearchlab.github.io/headless-cp-wf/how-to/run-without-docker/). The conda build uses Python 3.9.19 and NumPy 1.26.4,
  the container Python 3.8.0 and NumPy 1.24.4. On the test data, every feature value agreed with the container
  within a relative difference of 8e-6.
- Lab workstation with Docker: `-profile docker`. A workstation container needs `--privileged` and a volume on
  `/var/lib/docker`, or the Docker socket of the server. `scripts/start-docker-in-container.sh` checks this,
  applies the cgroup v2 fix and starts Docker. See [Run with Docker](https://mirandaresearchlab.github.io/headless-cp-wf/how-to/run-with-docker/).
- [Installation](https://mirandaresearchlab.github.io/headless-cp-wf/getting-started/installation/) installs Nextflow 26.04.6 and Java 21 with micromamba,
  the same way for both workstation modes.
- Berzelius: `scripts/berzelius/run_interactive.sh` runs your data inside an interactive job, with the local
  executor and the cores of the job. The guide now has three pages: [set up](https://mirandaresearchlab.github.io/headless-cp-wf/how-to/berzelius-setup/),
  [interactive run](https://mirandaresearchlab.github.io/headless-cp-wf/how-to/berzelius-interactive/) and [batch run](https://mirandaresearchlab.github.io/headless-cp-wf/how-to/berzelius-batch/).
- Removed: the `rootless` profile, its guide, `tests/test_rootless.py` and its CI job. They were for rootless
  Docker on the server itself, which is not a supported environment. Also removed: the guides "Run on a Slurm
  cluster", "Run on your own computer" and "Use the containers" (their content is in the new guides), and the
  old prototype archive `cellprofiler-nf.tar.gz`.
- Tests: `tests/reference/` holds the per-object features of the test data. The Docker and the no-Docker
  end-to-end tests compare every value with it. New stub tests check the profiles, `-resume`, a failed job
  (no new try) and a memory kill (a new try).
- CI: new jobs `workflow` (Ubuntu and macOS), `workstation-local` and `workstation-docker`.

### Added: image folder guide

- [Prepare your image folder](https://mirandaresearchlab.github.io/headless-cp-wf/how-to/format-image-folder/):
  folder layouts for one channel and for several channels, a `--group_regex` for each layout, a check with
  `-stub-run`, and how to name the channels in the NamesAndTypes module of your pipeline.

### Changed: Berzelius guide

- `smoke_test.sh` ran on a CPU node of the Ampere system and gave the expected 6 image sets and 51 nuclei.
- The guide explains the project account (it can differ from the folder name in `/proj`) and what to do if you
  cannot find it.
- Step 3 sets `PROJ` with `export` on the compute node, and loads `Miniforge3` without a version.
- `make_env.sh` replaces the copy-and-edit step. The template `berzelius.env.example` is gone.
- The troubleshooting table has new rows, and a new section tells how to solve a `mamba` lock.
- The default container is `cellprofiler/cellprofiler@sha256:...`, without the tag. Apptainer cannot pull a
  reference that has both a tag and a digest.

### Added: documentation site

- A documentation site with MkDocs and the Material theme, published on GitHub Pages at
  <https://mirandaresearchlab.github.io/headless-cp-wf/>. It has a tutorial, how-to guides, reference pages
  and explanations. `.github/workflows/docs.yml` builds it for each pull request and publishes it from `main`.
- `nextflow_schema.json` describes each parameter. The site makes its parameter reference from it, and
  `tests/test_schema.py` checks that it agrees with `nextflow.config`.
- The site makes its command-line and API reference pages from the `--help` text and the numpy docstrings of
  the scripts in `bin/`.
- The README is now short: what the workflow does, a quickstart, and links to the site.

### Changed: documentation

- The README now explains the workflow for a general audience, in simple English. It has a list of terms
  and a list of all checks.
- The information for developers moved to [Contributing](https://mirandaresearchlab.github.io/headless-cp-wf/about/contributing/).

### Fixed

- **Runs with masks failed after CellProfiler finished.** `check_chunk.py` used `str.removeprefix`, which needs
  Python 3.9. The CellProfiler 4.2.8 container has Python 3.8. Every run with `save_masks true` (the default)
  failed with `AttributeError`.
- **`--flag false` on the command line had the opposite effect.** Nextflow passes the value as the text
  `"false"`, and the workflow read any text as true. For example, `--gzip_features false` wrote `.csv.gz`
  files and `--allow_unpatched false` turned the fallback on. All boolean parameters now accept only
  `true` or `false`.
- `mask_manifest.csv` no longer contains `Metadata_FileLocation`, which held a path in the work folder.
- `scripts/test-nextflow.sh` and the workflow tests failed outside the activated `.venv`, and with Java 27
  (Nextflow supports Java 17 to 26). They now use `.venv/bin/nextflow` and find a supported Java
  themselves. Before, they changed Java only when `JAVA_HOME` was empty.
- **Nextflow on Berzelius ignored the Java of the conda environment.** Berzelius sets `JAVA_CMD=/usr/bin/java`
  (an old Java), and Nextflow reads `JAVA_CMD` before `JAVA_HOME`. It stopped with `Cannot find Java or it's a
  wrong version`. The settings file from `make_env.sh` now runs `unset JAVA_CMD` and sets `JAVA_HOME` after
  `conda activate`. Run `make_env.sh -f` again to update an old settings file. The guide has the same two
  lines in the check of step 3 and a row in the troubleshooting table.
- **The whole-workflow Docker image did not build.** Alpine's `sha256sum` has no `--check` option. The
  Dockerfile now uses `-c`.
- The whole-workflow image now makes its files readable for any `--user`. Before, a checkout with owner-only
  file modes gave an image that failed with `AccessDeniedException` for non-root users.

### Changed: runs that passed before can now stop

- **An incomplete image set stops the run.** All image sets must have the same number of files. Before, the
  workflow processed a site with a missing channel and gave no warning. Use `--allow_incomplete_sets true` to continue.
- **A file that does not match `--group_regex` stops the run.** Before, it became an image set of its own with a
  warning only. `--allow_incomplete_sets true` restores the old behaviour.
- **`strict_image_count` is now `true` by default.** If CellProfiler makes a different number of image sets than
  the workflow predicted, the chunk fails. The check now also runs when `chunk_size` is more than 0 without
  `--group_regex`. Before, multi-channel data split file by file passed without any check.
- **Chunking stops for pipelines that need all images in one run.** These are `CorrectIlluminationCalculate`
  in an "All" mode, `LoadData`, `Groups` with grouping on, `TrackObjects`, `MakeProjection`,
  `CalculateStatistics` and `Tile` across cycles. Before, each chunk calculated its own result, for example one
  illumination function per chunk, and the run did not report an error.
- **`--outdir` or the work folder inside `--input_dir` stops the run.** Before, a second run read the masks of
  the first run as input images.
- **`Count_<Object>` must agree with the object table.** A chunk fails if the per-image count and the number of
  rows in `<prefix><Object>.csv` are different.

### Changed: other

- After a real task error, running tasks finish before the workflow stops (`errorStrategy 'finish'`). Before, the
  workflow killed them (`'terminate'`), so their work was lost for `-resume`.
- The workflow pins the default container by digest: `cellprofiler/cellprofiler@sha256:fec440ca…`.
- CellProfiler runs with `QT_QPA_PLATFORM=offscreen`, `MPLBACKEND=Agg` and `-t` set to the task's temporary folder.
- The `slurm` profile moved to `conf/slurm.config`. It has new parameters: `slurm_account`, `slurm_partition`,
  `slurm_scratch` and `slurm_cluster_options`. The parameters also work from a `-c` config file. The job queue
  limit is now 100 (was 50).

### Added

- `--required_metadata`, for example `Plate,Well,Site`. Every image set must have non-empty, unique values.
- `pipeline_info/run_info.json` records the git commit, the Nextflow version, the container and all parameters.
- `logs/qc_<chunk>.json` records the number of images with zero objects for each object.
- `--container_cache` sets the Apptainer/Singularity image cache.
- Tests: helper tests on Python 3.8, Nextflow stub-run tests, and real CellProfiler tests in Docker, also in CI.
- Merging is faster for wide tables. The column union is now linear in the number of columns.
