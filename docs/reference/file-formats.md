# File formats

This page lists the columns and fields of each file that the workflow writes. The examples come from the
[tutorial](../tutorials/first-run.md) run. Where each file is: [Output](../output.md).

## Merged feature tables: `cellprofiler_tables/<Table>.csv`

CSV files, one per CellProfiler table (`Image.csv`, `Cells.csv`, `Nuclei.csv`, `Cytoplasm.csv`,
`Experiment.csv`), merged over all chunks of all plates. The names have no prefix, so they are the same in
every run. The columns are the columns of CellProfiler's ExportToSpreadsheet, with two columns in front:

| Column | Type | Description |
| --- | --- | --- |
| `CPNF_Chunk` | text | The chunk of the row, for example `PANC1_P01_chunk_0001` |
| `CPNF_ChunkImageNumber` | integer | The `ImageNumber` that CellProfiler wrote in that chunk (it starts at 1 in each chunk). Tables without `ImageNumber` (for example `Experiment.csv`) do not have this column. |
| `ImageNumber` | integer | The image number, unique over all plates and chunks: the merge rewrites it. The same value in the image table, the object tables and the mask list. |
| `ObjectNumber` | integer | Object tables only: the number of the object in its image. The same number is the value of the object in its mask. |
| `Metadata_Plate` | text | The plate: the plate folder (or `--plate_regex`). Every row of the image and object tables has it. |
| `Metadata_Well`, `Metadata_Site` | text | From the Metadata module of your pipeline. The object tables have them because the workflow sets "Add image metadata columns to your object data file" to Yes. |
| `Parent_Cells`, `Parent_Nuclei` | integer | `Cytoplasm.csv`: the `ObjectNumber` of the cell and of the nucleus of each cytoplasm object (from IdentifyTertiaryObjects). 0 = no parent. |
| *(other columns)* | | The measurements of CellProfiler, for example `AreaShape_Area`, `Intensity_MeanIntensity_CorrDNA`, `Count_Nuclei` |

If a column exists only in some chunks, its value is empty in the rows of the other chunks.

```text
CPNF_Chunk,CPNF_ChunkImageNumber,ImageNumber,ObjectNumber,Metadata_Plate,...,Metadata_Site,Metadata_Well,...
PANC1_P01_chunk_0002,1,51,1,PANC1_P01,...,1,A03,...
```

**One row per cell.** To join the compartments of each cell: take each row of `Cytoplasm.csv`, its cell is the
row of `Cells.csv` with the same `ImageNumber` and `ObjectNumber` = `Parent_Cells`, its nucleus is the row of
`Nuclei.csv` with the same `ImageNumber` and `ObjectNumber` = `Parent_Nuclei`, and its image is the row of
`Image.csv` with the same `ImageNumber`. With `--check_compartments true` (the default), the merge checks that
all these tables and columns exist.

## Mask list: `cellprofiler_tables/mask_manifest.csv`

One row per image set and object type.

| Column | Type | Description |
| --- | --- | --- |
| `CPNF_Chunk`, `CPNF_ChunkImageNumber` | text, integer | As in the feature tables |
| `ImageNumber` | integer | The image number, as in the feature tables. Join on it. |
| `Metadata_*` | text | The metadata of the image set, from the image table. The list leaves out `Metadata_FileLocation`, because it holds a temporary path. |
| `FileName_<channel>` | text | The file name of the channel image |
| `PathName_<channel>` | text | The folder of the channel image, relative to `--input_dir` |
| `InputPath_<channel>` | text | The path of the channel image, relative to `--input_dir` |
| `MaskObject` | text | The object type, for example `Nuclei` |
| `MaskPath` | text | The path of the mask, relative to `--outdir`: `<plate>/masks/...` |

The illumination functions (`FileName_Illum*`) are not channels of the list: they are the same for every site.

```text
CPNF_Chunk,CPNF_ChunkImageNumber,ImageNumber,Metadata_Plate,...,FileName_DNA,PathName_DNA,InputPath_DNA,MaskObject,MaskPath
plate1_chunk_0001,1,1,plate1,...,site0_DNA.tif,plate1,plate1/site0_DNA.tif,Nuclei,plate1/masks/site0_DNA_Nuclei_mask.tiff
plate1_chunk_0001,1,1,plate1,...,site0_DNA.tif,plate1,plate1/site0_DNA.tif,Cells,plate1/masks/site0_DNA_Cells_mask.tiff
```

## Masks: `<plate>/masks/<sub-folder>/<image>_<Object>_mask.<ext>`

| Property | Value |
| --- | --- |
| Format | `--mask_format`: `tiff` or `png` (16-bit integer image), or `npy` (NumPy array) |
| Pixel values | 0 = background. 1 to N = the objects. The value of an object is its `ObjectNumber`. |
| Size | The size of the input images |
| Name | The name of the first input image of the image set (the reference image), plus `_<Object>_mask` |

## Merge report: `cellprofiler_tables/merge_report.json`

| Field | Description |
| --- | --- |
| `chunks` | The number of chunks |
| `total_image_sets` | The number of image sets of all chunks |
| `tables.<name>.rows` | The number of rows of the merged table |
| `tables.<name>.columns` | The number of columns, with the `CPNF_` columns |
| `tables.<name>.chunks` | The number of chunks that had this table |

## Checks of a chunk: `logs/qc_<chunk>.json`

| Field | Description |
| --- | --- |
| `plate` | The plate of the chunk |
| `image_sets`, `expected_image_sets` | The image sets that CellProfiler made, and the number that the workflow predicted (-1 = no prediction) |
| `mask_files`, `expected_mask_files` | The mask files found, and the number expected (image sets × object types) |
| `mask_manifest_rows` | The rows in the mask list of the chunk |
| `images_without_objects` | For each object type: the number of image sets with zero objects |
| `tables` | For each table: its type (`image`, `object` or `other`), rows and columns |
| `warnings`, `errors` | The messages of the checks. A chunk with errors stops the run. |

```json
{
  "image_sets": 2, "expected_image_sets": 2,
  "mask_files": 4, "expected_mask_files": 4, "mask_manifest_rows": 4,
  "images_without_objects": {"Cells": 0, "Nuclei": 0},
  "warnings": [], "errors": []
}
```

## Illumination functions: `<plate>/illum/*.npy` and `logs/qc_illum_<plate>.json`

One NumPy file per SaveImages module of the illumination pipeline, for example `IllumDNA.npy`: a 2-D array of
floating-point numbers, the size of the images. The QC file has, for each function, its `shape`, `min`, `max`
and `mean`, and the `warnings` and `errors` of the check (one file per SaveImages module, finite values,
minimum > 0).

## Pipeline changes: `pipeline/patch_report.json`

| Field | Description |
| --- | --- |
| `cellprofiler_version` | The CellProfiler version that ran, for example `4.2.8` |
| `pipeline_date_revision` | The `DateRevision` of the input pipeline (428 = 4.2.8) |
| `objects` | The object types of the pipeline, in pipeline order |
| `masks_added`, `masks_managed` | The mask writers that the workflow added, and all its mask writers |
| `mask_reference_image` | The input image whose file names the masks get |
| `export_added` | `true` if the workflow added ExportToSpreadsheet |
| `export_changes` | The settings of ExportToSpreadsheet that the workflow changed (prefix, folder, metadata in object tables) |
| `cellpose_changes` | The RunCellpose modules that the workflow set to Python and no GPU |
| `images_filter_changes` | The filter of the Images module, changed to pass the `.npy` illumination functions |
| `illum`, `illum_outputs`, `illum_calculations` | Illumination pipeline (`illum_patch_report.json`): the functions that it calculates and saves |
| `removed_modules` | Modules that the workflow removed (CreateBatchFiles) |
| `redirected` | Output folders that the workflow moved into the job folder |
| `chunk_unsafe_modules` | Modules that need all image sets in one job |
| `unpatched` | `true` if the workflow ran the original pipeline (`--allow_unpatched`) |
| `warnings`, `errors` | Messages |

## Run report: `pipeline_info/run_info.json`

| Field | Description |
| --- | --- |
| `workflow` | Name, version, git commit (`-dirty` = uncommitted changes), repository and revision |
| `run` | Run name, session ID, start time, profiles, `-resume`, `-stub-run`, command line |
| `nextflow` | The Nextflow version |
| `container` | The container image of the CellProfiler jobs |
| `illumination` | `run` (`--illum_pipeline`), `reuse` (`--illum_dir`) or `none` |
| `plates` | For each plate: `sites`, `files`, `files_per_site` and `chunks` (written when the images are found) |
| `params` | All parameters of the run, as text |
