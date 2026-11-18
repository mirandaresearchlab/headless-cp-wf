# Documentation changes

This page records the scope of the documentation update.

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
