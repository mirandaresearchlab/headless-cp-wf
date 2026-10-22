# Changelog

## Unreleased

### Changed (breaking): plates, illumination per plate, one table for all plates

The input is now two pipelines and a folder with one sub-folder per plate. The output layout changed.

- **Plates.** Each file gets a plate: the first folder below `--input_dir`, or capture group 1 of the new
  `--plate_regex`. The run stops if a file has no plate, or a plate name has spaces or special characters.
  The image-set checks run per plate. Each plate is cut into its own chunks (a chunk never mixes plates),
  named after the plate: `PANC1_P01_chunk_0001`. The log and `run_info.json` show the sites and chunks of
  each plate.
- **Illumination (new process ILLUM).** `--illum_pipeline` runs once per plate, on all images of the plate.
  `bin/check_illum.py` checks one `.npy` file per SaveImages module, finite values and a minimum > 0. The
  functions go to `<outdir>/<plate>/illum/`. `--illum_dir` reuses the functions of an earlier run instead.
  Each analysis chunk gets the functions of its own plate only, after the images in its file list.
- **Merge.** One merge over all plates into `<outdir>/cellprofiler_tables/` (was `features/`), or one per
  plate with `--merge_all_plates false`. `ImageNumber` itself is now unique over all plates and chunks;
  `CPNF_ChunkImageNumber` keeps the value of the chunk (`CPNF_GlobalImageNumber` is gone). Every row of the
  image and object tables has `Metadata_Plate`.
- **Compartment check (`--check_compartments`, default true).** The merge stops if the Image, Cells, Nuclei
  or Cytoplasm table is missing, or a column that joins them into one row per cell (`ImageNumber`,
  `ObjectNumber`, `Parent_Cells`, `Parent_Nuclei`, plate, well, site), or if a plate, well and site occur
  twice. The merged tables are ready to be joined into single-cell profiles after the workflow.
- **Patch step.** ExportToSpreadsheet writes `Image.csv`, `Cells.csv`, ... without a prefix into the job
  folder, with the image metadata in the object tables. RunCellpose is set to Python and "Use GPU: No".
  The Images module passes the `.npy` functions ("Images only" dropped them).
- **Masks** go to `<outdir>/<plate>/masks/`. `--mask_objects` defaults to `Nuclei,Cells,Cytoplasm`.
- **Defaults.** `--chunk_size` 50 (was 0). `--plugins_dir` is `cp-plugins/` of the repository.
- **Cores and memory.** `--segmentation_cpus` (default 2) cores per analysis chunk, `--memory_per_cpu`
  (4 GB; 7 GB on Berzelius) per core. `--total_cpus` limits the cores of the whole run: `executor.cpus` on
  a workstation, `queueSize = total_cpus / segmentation_cpus` on Slurm (`total_cpus` 200) and Berzelius
  (64, so 32 chunks). `--total_memory` limits the memory of local runs. The memory of ILLUM and of the
  chunks doubles on each new try. Berzelius: ILLUM 1 core and 7 GB; chunks 2 cores and 14 GB.
- `trace.txt` also records the cores and the memory of each job.

### Added: containers and plugins

- `containers/cellprofiler-cellpose/`: CellProfiler 4.2.8 + Cellpose 3.1.1.2 + CPU PyTorch 2.4.1, the
  `nuclei` and `cyto3` models (checked by SHA-256), and the plugins. Every package is pinned.
- `cp-plugins/`: `runcellpose.py` and `enforceobjectsonetoone.py` from CellProfiler-plugins, commit
  `5aaa4e5`.
- The workflow stops before any job if a pipeline uses a plugin that `--plugins_dir` lacks, or uses
  RunCellpose in the official CellProfiler image (it has no Cellpose).

### Fixed: patch step and merge

- `patch_cppipe.py` failed on every pipeline whose Metadata module extracts metadata: the check of the new
  SaveImages modules needs Java, and the script did not start it.
- With `--required_metadata` and masks, the merge counted the rows of the mask list (one per mask) as the
  same site twice and stopped the run.

The CellProfiler measurements did not change. A run of the `test` profile gives the same Image, Nuclei and
Cells values as the original prototype, apart from work-folder paths and execution times.

### Added: Berzelius

- `-profile berzelius` runs the workflow on the Berzelius cluster (NSC). It follows the rules of the site:
  - All jobs go to a CPU partition (`berzelius-cpu` or `berzelius-hopper-cpu`). The workflow stops before it
    submits a job if the account is missing or if the partition is not a CPU partition.
  - Each job asks for at most 7 GB per core (an ILLUM job 1 core and 7 GB, an analysis chunk 2 cores and
    14 GB). Each new try doubles the cores and the memory.
  - Jobs run on the local disk `/scratch/local`. CellProfiler runs in Apptainer.
  - The run uses at most 64 cores at once (`--total_cpus`): 32 analysis chunks in the queue. No job asks for
    more than 72 hours.
  - The workflow stops if the work folder, the results or the image cache is in `$HOME`.
- `scripts/berzelius/`: `preflight.sh`, `smoke_test.sh`, `submit.sh`, the head job `run_nextflow.sbatch` and
  `make_env.sh`, which writes the settings file from options. A second `submit.sh` with the same run folder continues the run.
- [Berzelius: set up](https://mirandaresearchlab.github.io/headless-cp-wf/how-to/berzelius-setup/): the Berzelius guide.
- On a cluster, the workflow warns when more than 500 image sets of a plate run as one job (`chunk_size 0`).
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
