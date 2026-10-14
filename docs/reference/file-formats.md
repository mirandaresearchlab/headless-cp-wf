# File formats

This page lists the columns and fields of each file that the workflow writes. The examples come from the
[tutorial](../tutorials/first-run.md) run. Where each file is: [Output](../output.md).

## Merged feature tables: `features/<prefix><Table>.csv`

CSV files, one per CellProfiler table, merged over all chunks. The columns are the columns of
CellProfiler's ExportToSpreadsheet, with two columns in front:

| Column | Type | Description |
| --- | --- | --- |
| `CPNF_Chunk` | text | The chunk of the row, for example `chunk_0001` |
| `CPNF_GlobalImageNumber` | integer | The image number, unique in the complete run. Tables without `ImageNumber` (for example `Experiment.csv`) do not have this column. |
| `ImageNumber` | integer | CellProfiler's image number. It starts at 1 in each chunk. |
| `ObjectNumber` | integer | Object tables only: the number of the object in its image. The same number is the value of the object in its mask. |
| *(other columns)* | | The measurements of CellProfiler, for example `AreaShape_Area`, `Intensity_MeanIntensity_DNA`, `Count_Nuclei` |

If a column exists only in some chunks, its value is empty in the rows of the other chunks.

```text
CPNF_Chunk,CPNF_GlobalImageNumber,ImageNumber,ObjectNumber,AreaShape_Area,AreaShape_BoundingBoxArea,...
chunk_0001,1,1,1,55,90,...
```

## Mask list: `features/mask_manifest.csv`

One row per image set and object type.

| Column | Type | Description |
| --- | --- | --- |
| `CPNF_Chunk`, `CPNF_GlobalImageNumber` | text, integer | As in the feature tables. Join on `CPNF_GlobalImageNumber`. |
| `ImageNumber` | integer | CellProfiler's image number in the chunk |
| `Metadata_*` | text | The metadata of the image set, from the image table. The list leaves out `Metadata_FileLocation`, because it holds a temporary path. |
| `FileName_<channel>` | text | The file name of the channel image |
| `PathName_<channel>` | text | The folder of the channel image, relative to `--input_dir` |
| `InputPath_<channel>` | text | The path of the channel image, relative to `--input_dir` |
| `MaskObject` | text | The object type, for example `Nuclei` |
| `MaskPath` | text | The path of the mask, relative to `--outdir` |

```text
CPNF_Chunk,CPNF_GlobalImageNumber,ImageNumber,Metadata_Frame,Metadata_Series,FileName_DNA,PathName_DNA,InputPath_DNA,MaskObject,MaskPath
chunk_0001,1,1,0,0,site0_DNA.tif,plate1,plate1/site0_DNA.tif,Nuclei,masks/plate1/site0_DNA_Nuclei_mask.tiff
chunk_0001,1,1,0,0,site0_DNA.tif,plate1,plate1/site0_DNA.tif,Cells,masks/plate1/site0_DNA_Cells_mask.tiff
```

## Masks: `masks/<sub-folder>/<image>_<Object>_mask.<ext>`

| Property | Value |
| --- | --- |
| Format | `--mask_format`: `tiff` or `png` (16-bit integer image), or `npy` (NumPy array) |
| Pixel values | 0 = background. 1 to N = the objects. The value of an object is its `ObjectNumber`. |
| Size | The size of the input images |
| Name | The name of the first input image of the image set (the reference image), plus `_<Object>_mask` |

## Merge report: `features/merge_report.json`

| Field | Description |
| --- | --- |
| `chunks` | The number of chunks |
| `total_image_sets` | The number of image sets of all chunks |
| `tables.<name>.rows` | The number of rows of the merged table |
| `tables.<name>.columns` | The number of columns, with the two `CPNF_` columns |
| `tables.<name>.chunks` | The number of chunks that had this table |

## Checks of a chunk: `logs/qc_<chunk>.json`

| Field | Description |
| --- | --- |
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

## Pipeline changes: `pipeline/patch_report.json`

| Field | Description |
| --- | --- |
| `cellprofiler_version` | The CellProfiler version that ran, for example `4.2.8` |
| `pipeline_date_revision` | The `DateRevision` of the input pipeline (428 = 4.2.8) |
| `objects` | The object types of the pipeline, in pipeline order |
| `masks_added`, `masks_managed` | The mask writers that the workflow added, and all its mask writers |
| `mask_reference_image` | The input image whose file names the masks get |
| `export_added` | `true` if the workflow added ExportToSpreadsheet |
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
| `container` | The CellProfiler container with its digest |
| `params` | All parameters of the run, as text |
