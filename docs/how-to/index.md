# Find your guide

Find the row of your task. Each guide lists what you must do before it.

## Run the workflow

| Where you run | How CellProfiler runs | Guide |
| --- | --- | --- |
| Lab workstation (Ubuntu, you are `root`) | Without Docker, from a conda environment | [Installation](../getting-started/installation.md), then [Run without Docker](run-without-docker.md) |
| Lab workstation (Ubuntu, you are `root`) | In the official container, with Docker | [Installation](../getting-started/installation.md), then [Run with Docker](run-with-docker.md) |
| Berzelius, one node, for tests and small runs | In Apptainer | [Berzelius: set up](berzelius-setup.md), then [Berzelius: interactive run](berzelius-interactive.md) |
| Berzelius, Slurm jobs, for large runs | In Apptainer | [Berzelius: set up](berzelius-setup.md), then [Berzelius: batch run](berzelius-batch.md) |

## Prepare and check your data

| Task | Guide |
| --- | --- |
| Choose the parameters of a run: pipeline, images, grouping, chunks | [Run on your data](../usage.md) |
| Arrange images with one or more channels, and set `--group_regex` | [Prepare your image folder](format-image-folder.md) |
| Use your own CellProfiler pipeline, or change it safely | [Change the CellProfiler pipeline](change-pipeline.md) |
| Understand the result files | [Output](../output.md) |
| Find the cause of an error | [Troubleshooting](troubleshooting.md) |
