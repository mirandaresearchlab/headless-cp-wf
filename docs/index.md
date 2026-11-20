# Headless CellProfiler

This workflow turns microscopy images into cell measurements without opening the CellProfiler window.

You supply one folder per plate and two CellProfiler pipeline files.

!!! important "You must provide your own pipelines"
    The workflow does not create the pipelines. Provide `1_illumination.cppipe` and `2_analysis.cppipe`, made for your images.
    The files in `cp-configs/` are examples for one screen with five channels. They may not fit your images.
    See [provide your own pipelines](usage.md#provide-your-own-pipelines).

The workflow corrects uneven lighting, finds objects, measures them, and checks the outputs.
It saves label masks and one Parquet table per plate with one row per cell.

```mermaid
flowchart LR
    A[Plate images and two pipelines] --> B[PREPARE: check inputs]
    B --> C[ILLUMINATION: one job per plate]
    B --> D[ANALYSIS: one job per batch]
    C --> D
    D --> E[MERGE: one job per plate]
    E --> G[Cell table per plate: Parquet]
    D --> H[Label masks]
```

## Start here

1. Follow [installation](getting-started/installation.md).
2. Complete the [first-run tutorial](tutorials/first-run.md).
3. [Run your own images](usage.md).
4. Read [outputs and checks](output.md) before using the measurements.

For failures, use [troubleshooting](how-to/troubleshooting.md).
For job dependencies, read [how jobs run](explanation/workflow.md).

## What this version supports

| Item | Support |
|---|---|
| Input images | Single-plane, unsigned 8-bit or 16-bit grayscale TIFFs |
| Channels of the example pipelines | DNA, RNA, AGP, Mito, ER |
| Segmentation | Traditional nuclei detection and watershed cell segmentation |
| Execution | Local workstation or the supplied Berzelius Slurm profile |
| CellProfiler | Exactly 4.2.8.1 for both CellProfiler packages |
| Nextflow | At least 25.10.4 in the repository configuration |

There is no `test` profile. The repository does not include images.
See [validation status](about/contributing.md#validation-status) for what was checked in this documentation update.
