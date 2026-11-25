# Documentation changes

This page records the scope of the documentation update.

## No warning for an empty Cellpose model folder

- Nextflow warned once for every task: ``Environment variable `CELLPOSE_LOCAL_MODELS_PATH` evaluates to an empty value``.
  The workflow now sets the variable only when you give `--cellpose_models`. Without it, Cellpose uses
  `~/.cellpose/models`, as before. The results do not change.

## Extra options for `berzelius-run-plates.sbatch`

- New setting `NF_ARGS` passes extra Nextflow options to every plate, for example
  `--segmentation gpu`. See [Run one plate at a time](../how-to/run-on-hpc.md#run-one-plate-at-a-time-when-disk-space-is-short).

## Segmentation only

- New parameter `--segmentation_only` (issue #3): the run stops after SEGMENT and publishes each
  batch folder of Cellpose-SAM masks to `masks/<plate>/<batch>/`. ANALYSIS and MERGE do not run.
  A later run without the flag and with `-resume` reuses ILLUMINATION and SEGMENT.
  See [segment only](../usage.md#segment-only), and for Berzelius
  [Segment with Cellpose-SAM on a GPU](../how-to/run-on-hpc.md#segment-with-cellpose-sam-on-a-gpu).
- It needs RunCellpose in `2_analysis.cppipe`. A classic pipeline segments inside ANALYSIS, so the run stops with a message.

## Stub test of the whole workflow

- Each process has a `stub:` block, and `tests/test_workflow_stub.py` runs `main.nf` with
  `nextflow run -stub` for the classic and the Cellpose configuration (issue #14).
  It checks the joins between plates, batches, illumination, SEGMENT and MERGE, and the `--project`
  output folder. GitHub runs it in the new `workflow-stub` job. See
  [contributing](contributing.md#test-the-whole-workflow-with-stubs).
- `prepare.py --stub` plans the batches without CellProfiler. Only the stub run uses it.

## Adaptive threshold window check

- PREPARE stops the run if an adaptive threshold window of either pipeline is more than half of the
  shorter image side of a plate (issue #11). Before, CellProfiler stopped in ANALYSIS with
  `Adaptive window cannot exceed 50% of an image dimension`, after ILLUMINATION was complete.
- The rule is the one of CellProfiler 4.2.8.1. Windows that CellProfiler does not use are not checked:
  a disabled module, a Global or Sauvola threshold, IdentifyPrimaryObjects without advanced settings,
  and IdentifySecondaryObjects with Distance - N.
- `contract.json` records the checked windows (`adaptive_windows`).

## Retries with more resources

- A task that Slurm stops at its time limit (exit status 140) is now retried, like exit statuses 137 and 143 (issue #12).
  Before, it stopped the whole run.
- Each retry asks for more memory and time: attempt 2 gets twice `--task_memory` and `--task_time`, attempt 3 three times.
  The request never goes above `--total_memory` (local) or one Berzelius CPU node (960 GB) and 72 hours.
- The Berzelius profile now really uses `--max_retries 2`. Before, tasks were retried only once, because the default of 1 was read first.

## Image set order

- PREPARE sorts the image sets of a plate by well, then site, then the other metadata. Numbers compare as numbers: site 2 comes before site 10.
  Before, the order came from the metadata names in alphabetical order, with values compared as text (issue #15).
- The measurements do not change. Which image sets share a batch, and `Metadata_PlateImageNumber`, do change.
  Do not join outputs of runs before and after this change on `Metadata_PlateImageNumber`; use plate, well and site.
  A run that was started before this change cannot `-resume` its ANALYSIS and MERGE tasks.

## Cellpose-SAM

- `2_analysis.cppipe` can use RunCellpose with Cellpose-SAM (Cellpose 4). A new SEGMENT step runs it on a GPU or on CPUs
  (`--segmentation gpu` or `cpu`). ANALYSIS loads the masks with the new LoadLabelMasks module and measures on CPUs.
  See [segmentation choices](../explanation/segmentation.md#cellpose-sam).
- New parameters: `--segmentation`, `--segmentation_batches`, `--segmentation_workers`, `--cellpose_models`, and for Berzelius `--gpu_partition`, `--gpu_cpus` and `--max_gpus`.
- `cp-configs-cellpose/` is an example configuration with Cellpose-SAM nuclei.
- `plugins/runcellpose.py` is a copy of the RunCellpose plugin with three corrections for Cellpose 4 (listed at its top).
- `environment.yml` installs cellpose 4.0.6 and PyTorch 2.5.1 (CUDA 12.1) with pip.
- MERGE now stops if a nucleus or a cytoplasm names a cell that does not exist. Before, MERGE left such an object out of the table without a message.
  `merge.json` has the new field `objects`: the number of cells, cytoplasms and nuclei that CellProfiler counted.
- PREPARE stops if the nuclei or the cytoplasm have no `Parent_<cells>` measurement. Before, MERGE failed at the end of the run.
- The classic pipeline (`cp-configs/`) gives the same per-cell table and masks as before.

## Code tidy-up

- The workflow takes only a samplesheet (`--input`). The `--images` folder input is gone.
  `bin/make_samplesheet.py` writes a samplesheet for a folder of plate folders.
- The Nextflow code follows the nf-core layout: `workflows/`, `modules/local/` and `conf/` (was `nf-config/`).
- The parameters are in `nextflow.config` only. The unused Conda settings and `--conda_cache` are gone.
- Fixed: a new run did not use the `--project` name. The results went to a folder with the session ID as its name.
- `tests/make_fixture.py` makes 1024 × 1024 crops. The 512 × 512 crops failed with the example analysis pipeline.
- Deleted `bin/convert_watershed.py`, `tests/benchmark.nf`, `tests/compare_runs.py` and the `test-images` link.
- The Berzelius scripts take a samplesheet. The plate script uses `SHEET` instead of `DATA`.
- Python functions use NumPy-style docstrings. Long functions are split into smaller ones. The results do not change.

## Berzelius scripts

- Added `scripts/berzelius-interactive.sh`. It runs the workflow inside an interactive session, for tests.
- Added `scripts/berzelius-run.sbatch`. It runs Nextflow as a Slurm head job, for full screens.
- Rewrote [Run on Berzelius](../how-to/run-on-hpc.md): setup, both ways to run, resume and common problems.
- Added the [Berzelius FAQ](../how-to/berzelius-faq.md): cores, memory, cost and job placement.
- Added `scripts/berzelius-run-plates.sbatch`. It runs one plate at a time and deletes the work files of each finished plate.
- Each project now starts Nextflow from its own folder, `$PROJ/runs/<project>-launch`. Before, projects that started from the repository folder shared one session and one results folder.
- Added the disk space, job check and node questions to the FAQ. Changed the suggested `--max_jobs` to 64 to 96.
- Added the note that users must provide their own `1_illumination.cppipe` and `2_analysis.cppipe`: README, home page, [usage](../usage.md#provide-your-own-pipelines), the Berzelius guide and the FAQ.
- Added the FAQ section [When a job stops or fails](../how-to/berzelius-faq.md#when-a-job-stops-or-fails). Changed the suggested `--task_time` to 4 hours, because tasks of a slower plate took up to 113 minutes.

## First documentation update

The MkDocs guide adds installation, a cropped-data tutorial, job diagrams, input and output reference,
resource planning, cluster instructions, and troubleshooting.
It replaces incorrect cleanup guidance: both supplied profiles preserve work files.
It explains that users must activate the CellProfiler environment because no process declares one.

No scientific algorithm, workflow parameter, or runtime behavior changed in this documentation update.
The repository does not include a release changelog.
See [validation status](contributing.md#validation-status) for verification limits.
