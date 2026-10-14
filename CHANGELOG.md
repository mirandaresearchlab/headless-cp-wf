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
- `scripts/berzelius/`: `preflight.sh`, `smoke_test.sh`, `submit.sh`, the head job `run_nextflow.sbatch` and a
  template for the settings file. A second `submit.sh` with the same run folder continues the run.
- [Run on Berzelius](https://mirandaresearchlab.github.io/headless-cp-wf/how-to/run-on-berzelius/): a guide in eight steps.
- On a cluster, the workflow warns when more than 500 image sets run as one job (`chunk_size 0`).
- CellProfiler jobs ignore your own Python packages (`PYTHONNOUSERSITE=1`).

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
- The workflow pins the default container by digest: `cellprofiler/cellprofiler:4.2.8@sha256:fec440ca…`.
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
