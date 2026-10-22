# Change the CellProfiler pipeline

This guide tells you how to use your own CellProfiler pipeline with the workflow, and how to check it before a
large run. The requirements are in [CellProfiler pipelines](../reference/pipelines.md).

!!! info "Before you start"
    This page assumes that you installed the workflow and ran its test. On a lab workstation, see
    [Installation](../getting-started/installation.md). On Berzelius, see [Berzelius: set up](berzelius-setup.md). To check, open a terminal in the
    folder `headless-cp-wf` and run `nextflow -version`. It must print a version number.

## 1. Make or change the pipelines in CellProfiler 4.2.8

The workflow takes two pipelines: an illumination pipeline (`--illum_pipeline`, it runs once per plate) and an
analysis pipeline (`--pipeline`, it runs in chunks). The PANC1 pipelines in `cp-configs/` are an example. Use
the same CellProfiler version as the container. A pipeline from a newer CellProfiler can fail to load, or can
give different results. Check the header of each `.cppipe` file:

```text
CellProfiler Pipeline: http://www.cellprofiler.org
Version:5
DateRevision:428
```

`DateRevision:428` means CellProfiler 4.2.8.

In the illumination pipeline:

- Calculate one function per channel with CorrectIlluminationCalculate ("All: Across cycles").
- Save each function with SaveImages: format `npy`, "Last cycle". The workflow checks one `.npy` file per
  SaveImages module.

In the analysis pipeline:

- Find the images with the Images, Metadata and NamesAndTypes modules. Do not use LoadData: the work is divided
  into chunks.
- Load each illumination function in NamesAndTypes by its name (for example "file starts with IllumDNA"), as
  type "Illumination function", and apply it with CorrectIlluminationApply. Do not calculate illumination
  functions here.
- Extract well and site with the Metadata module. The workflow adds the plate from the plate folder.
- Name the objects `Nuclei`, `Cells` and `Cytoplasm` (IdentifyTertiaryObjects), or set `--mask_objects` and
  `--check_compartments false`.
- You do not need to add mask saving or ExportToSpreadsheet, and you can keep RunCellpose set to Docker: the
  workflow adds the masks and the export, and sets RunCellpose to Python without a GPU.

## 2. Test the pipelines on a few images

Copy the images of a few sites into a test folder, with one sub-folder per plate (for example
`test_images/PANC1_P01/`). First do a dry run. It checks the plates, the grouping and your parameters in
seconds, and it does not start CellProfiler:

```bash
nextflow run . -profile local -stub-run \
    --illum_pipeline 1_illumination.cppipe --pipeline 2_analysis_cellpose.cppipe \
    --input_dir test_images --outdir test_stub --group_regex '^(.+?_s\d+)_x' --chunk_size 2
```

Then run the workflow on the same folder with real CellProfiler. A pipeline with RunCellpose needs the
Cellpose image (`--container`, see `containers/README.md`):

```bash
nextflow run . -profile docker \
    --illum_pipeline 1_illumination.cppipe --pipeline 2_analysis_cellpose.cppipe \
    --input_dir test_images --outdir test_results --group_regex '^(.+?_s\d+)_x' --chunk_size 2 \
    --container <the Cellpose image>
```

## 3. Read the reports

- `test_results/pipeline/patch_report.json` and `illum_patch_report.json`: the changes that the workflow made.
  Look at `objects` (the object types that it found), `redirected` (output folders that it moved),
  `illum_outputs` (the illumination functions) and `warnings`.
- `test_results/logs/qc_illum_<plate>.json`: the illumination functions of each plate (minimum, maximum, mean).
- `test_results/logs/qc_<plate>_chunk_0001.json`: the checks of the first chunk of a plate. `errors` must be
  empty.
- `test_results/cellprofiler_tables/merge_report.json`: the number of rows of each table.

Open `test_results/pipeline/patched.cppipe` in CellProfiler to see the pipeline that ran.

## 4. Look at the masks

Open some masks from `test_results/<plate>/masks/` in an image viewer (for example Fiji) next to their input images.
Check that the objects look correct before you run the complete data.
