# Tutorial: first run on the test data

**You will:** run CellProfiler on 6 small test images, look at the tables and masks, and read the reports.
**Time:** less than a minute for the run, plus the download of the CellProfiler image the first time (with Docker).
**Prerequisites:** a lab workstation with the workflow installed ([Installation](../getting-started/installation.md)).
CellProfiler must be ready in one of two ways: [without Docker](../how-to/run-without-docker.md) (steps 1 to 3)
or [with Docker](../how-to/run-with-docker.md) (steps 1 and 2). On Berzelius, use
[Berzelius: set up](../how-to/berzelius-setup.md) instead. Its step 5 runs the same test data.

## 1. Look at the test data

The repository contains 6 test images (128 × 128 pixels, 16-bit, one DNA channel) in two plate folders.
The name of each folder is the name of its plate:

```text
tests/images/
├── plate1/  site0_DNA.tif  site1_DNA.tif  site2_DNA.tif
└── plate2/  site0_DNA.tif  site1_DNA.tif  site2_DNA.tif
```

The test pipeline `tests/test.cppipe` finds the nuclei, grows them into cells, and measures their size,
shape and DNA intensity. It is one pipeline without illumination correction: your own runs usually add an
illumination pipeline (`--illum_pipeline`), see [Run on your data](../usage.md). See also
[CellProfiler pipelines](../reference/pipelines.md).

## 2. Run the workflow

=== "Without Docker"

    ```bash
    nextflow run . -profile test,local -c local.config
    ```

    The `local` profile runs CellProfiler from your conda environment. `local.config` gives the jobs the
    Java of CellProfiler.

=== "With Docker"

    ```bash
    nextflow run . -profile test,docker
    ```

    The `docker` profile runs CellProfiler in the official container.

The `test` profile sets the pipeline, the image folder, `--chunk_size 2` (2 image sets per job),
`--group_regex '^(.+)$'` (each file is one image set) and `--total_cpus 2`. The test pipeline has no
Cytoplasm, so the profile also sets `--mask_objects Nuclei,Cells` and `--check_compartments false`. The output starts
like this:

```text
==================================  cp-headless  ==================================
pipeline       : <repo>/tests/test.cppipe
illumination   : none
input_dir      : <repo>/tests/images
plates         : first folder below input_dir
outdir         : results_test
group_regex    : ^(.+)$
chunk_size     : 2
cores          : 2 per chunk, 2 in total -> 1 chunk(s) at once
merge          : all plates into one table
save_masks     : true (tiff)
container      : cellprofiler/cellprofiler@sha256:fec440ca...
=================================================================================
[cp-headless] 2 plate(s): 6 image set(s), 6 file(s) -> 4 chunk(s)
[cp-headless] plate1: 3 image set(s) of 1 file(s), 2 chunks x 2 cores x 8 GB
[cp-headless] plate2: 3 image set(s) of 1 file(s), 2 chunks x 2 cores x 8 GB
```

Then Nextflow shows the jobs: `PATCH_PIPELINE`, four times `CELLPROFILER` (`plate1_chunk_0001`,
`plate1_chunk_0002`, `plate2_chunk_0001`, `plate2_chunk_0002`) and `MERGE_FEATURES`. The look of these lines
depends on your terminal and on the Nextflow installation. The run must end without `ERROR`. (The line
`container` shows the default image also with the `local` profile. The `local` profile does not use it.)

Six jobs ran: one job prepared the pipeline, four CellProfiler jobs ran (one per chunk; each plate has its own
chunks, so plate1 with 3 sites gives a chunk of 2 and a chunk of 1), and one job merged the tables of both
plates. With `--total_cpus 2` and 2 cores per chunk, one chunk ran at a time; the others waited.

## 3. Look at the results

```text
results_test/
├── cellprofiler_tables/  Image.csv  Nuclei.csv  Cells.csv  Experiment.csv
│                         mask_manifest.csv  merge_report.json
├── plate1/masks/         site0_DNA_Nuclei_mask.tiff  site0_DNA_Cells_mask.tiff  ... (6 files)
├── plate2/masks/         ... (6 files)
├── logs/                 log_plate1_chunk_0001.txt ... qc_plate1_chunk_0001.json ...
├── pipeline/             patched.cppipe  patch_report.json
└── pipeline_info/        run_info.json  report.html  timeline.html  trace.txt
```

With your own pipelines, the results also have `<plate>/illum/` (the illumination functions), and a
`Cytoplasm.csv` that joins each cell with its nucleus. See [Output](../output.md).

**The tables.** `cellprofiler_tables/merge_report.json` gives the size of each merged table:

```json
"Image.csv":  {"rows": 6,  "columns": 55, "chunks": 4},
"Nuclei.csv": {"rows": 51, "columns": 86, "chunks": 4},
"Cells.csv":  {"rows": 51, "columns": 86, "chunks": 4}
```

The image table has one row per image set (6, from both plates). The Nuclei table has one row per nucleus (51
in all images). Each row starts with columns that the workflow adds:

```text
CPNF_Chunk,CPNF_ChunkImageNumber,ImageNumber,ObjectNumber,Metadata_Plate,AreaShape_Area,...
plate1_chunk_0001,1,1,1,plate1,55,...
```

CellProfiler starts `ImageNumber` at 1 in each chunk. The merge makes `ImageNumber` unique over both plates
(1 to 6) and keeps the original number in `CPNF_ChunkImageNumber`. Use `ImageNumber` to join the tables.
`Metadata_Plate` comes from the plate folder.

**The masks.** `plate1/masks/` and `plate2/masks/` have one 16-bit mask per image set and object type: 6 image
sets × 2 objects (Nuclei, Cells) = 12 files. In a mask, the pixels of object 1 have the value 1, and so on. The
value 0 is the background. `cellprofiler_tables/mask_manifest.csv` connects each mask to its image set:

```text
CPNF_Chunk,CPNF_ChunkImageNumber,ImageNumber,Metadata_Plate,...,InputPath_DNA,MaskObject,MaskPath
plate1_chunk_0001,1,1,plate1,...,plate1/site0_DNA.tif,Nuclei,plate1/masks/site0_DNA_Nuclei_mask.tiff
```

**The checks.** `logs/qc_plate1_chunk_0001.json` shows the checks of one chunk:

```json
"plate": "plate1",
"image_sets": 2, "expected_image_sets": 2,
"mask_files": 4, "expected_mask_files": 4,
"images_without_objects": {"Cells": 0, "Nuclei": 0},
"warnings": [], "errors": []
```

**The changes to the pipeline.** `pipeline/patch_report.json` lists them. For the test pipeline, the
workflow removed `CreateBatchFiles`, added a spreadsheet export without a file name prefix, and added mask
writers for Nuclei and Cells.

**The run report.** `pipeline_info/run_info.json` records the git commit, the Nextflow version, the
container, all parameters of the run, and the plates with their sites and chunks.

## 4. Run it again with `-resume`

Run the command of step 2 again and add `-resume`, for example:

```bash
nextflow run . -profile test,docker -resume
```

Nextflow uses the results of the first run and runs no job again. It shows the 6 jobs as cached.

## Next steps

- Run the workflow on your own images: [Run on your data](../usage.md).
- Learn what each output file contains: [Output](../output.md).
