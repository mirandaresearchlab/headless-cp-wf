# Documentation changes

This page records the scope of the documentation update.

## Berzelius scripts

- Added `scripts/berzelius-interactive.sh`. It runs the workflow inside an interactive session, for tests.
- Added `scripts/berzelius-run.sbatch`. It runs Nextflow as a Slurm head job, for full screens.
- Rewrote [Run on Berzelius](../how-to/run-on-hpc.md): setup, both ways to run, resume and common problems.
- Added the [Berzelius FAQ](../how-to/berzelius-faq.md): cores, memory, cost and job placement.

## First documentation update

The MkDocs guide adds installation, a cropped-data tutorial, job diagrams, input and output reference,
resource planning, cluster instructions, and troubleshooting.
It replaces incorrect cleanup guidance: both supplied profiles preserve work files.
It explains that users must activate the CellProfiler environment because no process declares one.

No scientific algorithm, workflow parameter, or runtime behavior changed in this documentation update.
The repository does not include a release changelog.
See [validation status](contributing.md#validation-status) for verification limits.
