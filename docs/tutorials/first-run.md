# Tutorial: first run on the test data

**You will:** run CellProfiler on 6 small test images, look at the tables and masks, and read the reports.
**Time:** about 10 seconds for the run, plus the download of the CellProfiler image the first time.
**Prerequisites:** [Installation](../getting-started/installation.md) and Docker.

## 1. Look at the test data

The repository contains 6 test images (128 × 128 pixels, 16-bit, one DNA channel) in two folders:

```text
tests/images/
├── plate1/  site0_DNA.tif  site1_DNA.tif  site2_DNA.tif
└── plate2/  site0_DNA.tif  site1_DNA.tif  site2_DNA.tif
```

The test pipeline `tests/test.cppipe` finds the nuclei, grows them into cells, and measures their size,
shape and DNA intensity. See [CellProfiler pipelines](../reference/pipelines.md).

## 2. Run the workflow

```bash
nextflow run . -profile test,docker
```

The `test` profile sets the pipeline, the image folder, `--chunk_size 2` (2 image sets per job) and
`--group_regex '^(.+)$'` (each file is one image set). The `docker` profile runs CellProfiler in Docker.

The output is:

```text
==================================  cp-headless  ==================================
pipeline     : <repo>/tests/test.cppipe
input_dir    : <repo>/tests/images
outdir       : results_test
group_regex  : ^(.+)$
chunk_size   : 2
save_masks   : true (tiff)
container    : cellprofiler/cellprofiler:4.2.8@sha256:fec440ca...
=================================================================================
[cp-headless] image sets have 1 file(s) each (most common size)
[cp-headless] 6 image set(s), 6 file(s) -> 3 chunk(s)
[PROCESS 8b/0888ea] PATCH_PIPELINE (original/test.cppipe)
[PROCESS a6/dca722] CELLPROFILER (chunk_0001 (2 sets, 2 files))
[PROCESS e2/563895] CELLPROFILER (chunk_0003 (2 sets, 2 files))
[PROCESS b9/8c8fbc] CELLPROFILER (chunk_0002 (2 sets, 2 files))
[PROCESS 02/dfa794] MERGE_FEATURES

[SUCCESS] completed=5 failed=0 cached=0
```

Five jobs ran: one job prepared the pipeline, three CellProfiler jobs ran at the same time (one per
chunk), and one job merged the tables.

## 3. Look at the results

```text
results_test/
├── features/        MyExpt_Image.csv  MyExpt_Nuclei.csv  MyExpt_Cells.csv  MyExpt_Experiment.csv
│                    mask_manifest.csv  merge_report.json
├── masks/           plate1/site0_DNA_Nuclei_mask.tiff  plate1/site0_DNA_Cells_mask.tiff  ... (12 files)
├── logs/            log_chunk_0001.txt ... qc_chunk_0001.json ...
├── pipeline/        patched.cppipe  patch_report.json
└── pipeline_info/   run_info.json  report.html  timeline.html  trace.txt
```

**The tables.** `features/merge_report.json` gives the size of each merged table:

```json
"MyExpt_Image.csv":  {"rows": 6,  "columns": 54, "chunks": 3},
"MyExpt_Nuclei.csv": {"rows": 51, "columns": 85, "chunks": 3},
"MyExpt_Cells.csv":  {"rows": 51, "columns": 85, "chunks": 3}
```

The image table has one row per image set (6). The Nuclei table has one row per nucleus (51 in all images).
Each row starts with two columns that the workflow adds:

```text
CPNF_Chunk,CPNF_GlobalImageNumber,ImageNumber,ObjectNumber,AreaShape_Area,...
chunk_0001,1,1,1,55,...
```

CellProfiler starts `ImageNumber` at 1 in each chunk. `CPNF_GlobalImageNumber` is unique in the complete
run. Use it to join the tables.

**The masks.** `masks/` has one 16-bit mask per image set and object type: 6 image sets × 2 objects
(Nuclei, Cells) = 12 files. In a mask, the pixels of object 1 have the value 1, and so on. The value 0 is
the background. `features/mask_manifest.csv` connects each mask to its image set:

```text
CPNF_Chunk,CPNF_GlobalImageNumber,ImageNumber,...,InputPath_DNA,MaskObject,MaskPath
chunk_0001,1,1,...,plate1/site0_DNA.tif,Nuclei,masks/plate1/site0_DNA_Nuclei_mask.tiff
```

**The checks.** `logs/qc_chunk_0001.json` shows the checks of one chunk:

```json
"image_sets": 2, "expected_image_sets": 2,
"mask_files": 4, "expected_mask_files": 4,
"images_without_objects": {"Cells": 0, "Nuclei": 0},
"warnings": [], "errors": []
```

**The changes to the pipeline.** `pipeline/patch_report.json` lists them. For the test pipeline, the
workflow removed `CreateBatchFiles`, added a spreadsheet export, and added mask writers for Nuclei and Cells.

**The run report.** `pipeline_info/run_info.json` records the git commit, the Nextflow version, the
container and all parameters of the run.

## 4. Run it again with `-resume`

```bash
nextflow run . -profile test,docker -resume
```

Nextflow uses the results of the first run and runs no job again: `cached=5`.

## Next steps

- Run the workflow on your own images: [Run on your data](../usage.md).
- Learn what each output file contains: [Output](../output.md).
