# Change the CellProfiler pipeline

This guide tells you how to use your own CellProfiler pipeline with the workflow, and how to check it before a
large run. The requirements are in [CellProfiler pipelines](../reference/pipelines.md).

!!! info "Before you start"
    This guide assumes that you cloned the repository, installed the tools and activated the environment.
    If you did not, do [Installation](../getting-started/installation.md) first. To check, open a terminal in the folder `headless-cp-wf`
    and run `source .venv/bin/activate` and then `nextflow -version`. It must print a version number.

## 1. Make or change the pipeline in CellProfiler 4.2.8

Use the same CellProfiler version as the container. A pipeline from a newer CellProfiler can fail to load, or
can give different results. Check the header of the `.cppipe` file:

```text
CellProfiler Pipeline: http://www.cellprofiler.org
Version:5
DateRevision:428
```

`DateRevision:428` means CellProfiler 4.2.8.

In the pipeline:

- Find the images with the Images, Metadata and NamesAndTypes modules. Do not use LoadData if you want to
  divide the work into chunks.
- Extract plate, well and site with the Metadata module if you want to use `--required_metadata`.
- You do not need to add mask saving or ExportToSpreadsheet. The workflow adds them.

## 2. Test the pipeline on a few images

Copy the images of a few sites into a test folder. First do a dry run. It checks the grouping and your
parameters in seconds, and it does not start CellProfiler:

```bash
nextflow run . -profile local -stub-run \
    --pipeline analysis.cppipe --input_dir test_images --outdir test_stub \
    --group_regex '^(.+?_s\d+)_w\d' --chunk_size 2
```

Then run the workflow on the same folder with real CellProfiler:

```bash
nextflow run . -profile docker \
    --pipeline analysis.cppipe --input_dir test_images --outdir test_results \
    --group_regex '^(.+?_s\d+)_w\d' --chunk_size 2
```

## 3. Read the reports

- `test_results/pipeline/patch_report.json`: the changes that the workflow made. Look at `objects` (the
  object types that it found), `redirected` (output folders that it moved) and `warnings`.
- `test_results/logs/qc_chunk_0001.json`: the checks of the first chunk. `errors` must be empty.
- `test_results/features/merge_report.json`: the number of rows of each table.

Open `test_results/pipeline/patched.cppipe` in CellProfiler to see the pipeline that ran.

## 4. Look at the masks

Open some masks from `test_results/masks/` in an image viewer (for example Fiji) next to their input images.
Check that the objects look correct before you run the complete data.
