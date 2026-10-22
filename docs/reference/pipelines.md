# CellProfiler pipelines

This page lists what the workflow needs from your two CellProfiler pipelines, what it changes in them, and
describes the test pipelines of the repository. How to use your own pipeline:
[Change the CellProfiler pipeline](../how-to/change-pipeline.md).

You give the workflow two pipelines, made in the CellProfiler program:

| Pipeline | Parameter | Runs | Example |
| --- | --- | --- | --- |
| Illumination | `--illum_pipeline` | once per plate, on all its images | `1_illumination.cppipe` |
| Analysis | `--pipeline` | in chunks of `--chunk_size` sites | `2_analysis_cellpose.cppipe` |

## Requirements for both pipelines

| Requirement | Why |
| --- | --- |
| Made in CellProfiler 4.2.8 (`DateRevision: 428`), or set `--container` to its version | A pipeline from a newer version can fail to load, or give different results |
| Finds its images with Images, Metadata and NamesAndTypes | The workflow gives each job a list of files (`--file-list`) |
| NamesAndTypes groups the files as `--group_regex` does | Otherwise the image-set count check stops the run |
| Plugins (RunCellpose, EnforceObjectsOneToOne) in `--plugins_dir` | CellProfiler must find them in each job. The default is `cp-plugins/` of the repository. |

## Requirements for the illumination pipeline

| Requirement | Why |
| --- | --- |
| CorrectIlluminationCalculate, usually "All: Across cycles" | It calculates one function per channel from all images of the plate |
| One SaveImages per function: format `npy`, when to save "Last cycle" | Only at the last cycle does the function hold all images. The workflow checks one `.npy` file per SaveImages module. |

## Requirements for the analysis pipeline

| Requirement | Why |
| --- | --- |
| NamesAndTypes loads each function by name, as type "Illumination function", without metadata matching (for example the rule "file startswith IllumDNA and endswith .npy") | The workflow adds the `.npy` files of the plate to the file list of each chunk. Each site gets the same functions. |
| CorrectIlluminationApply divides each channel by its function | |
| No module that needs all image sets (see the list below) | Each chunk is a separate CellProfiler run |
| The Metadata module extracts `Well` and `Site` | The merge needs plate, well and site in every row, to join the tables of each cell. The workflow adds the plate. |
| Objects named `Nuclei`, `Cells` and `Cytoplasm` (IdentifyTertiaryObjects) | The masks (`--mask_objects`) and the compartment check (`--check_compartments`) use these names. Other names: set `--mask_objects` and `--check_compartments false`. |

**What the workflow changes in the analysis pipeline** (each change is in `pipeline/patch_report.json`):

| Module | Change | Why |
| --- | --- | --- |
| RunCellpose | Run in **Python** (not Docker), Use GPU **No** | Berzelius CPU nodes have no Docker and no GPU. The container has Cellpose and its models. |
| Images | "Images only" becomes a custom rule that also passes `.npy` files | "Images only" drops the illumination functions |
| ExportToSpreadsheet | No file name prefix, Default Output Folder, image metadata in object tables, one file per object | The same names in every run (`Image.csv`, `Cells.csv`, `Nuclei.csv`, `Cytoplasm.csv`), with plate, well and site in every table |
| (new) ConvertObjectsToImage + SaveImages | One 16-bit mask per site and object of `--mask_objects` | Masks for every object. Do not add your own mask modules. |
| CreateBatchFiles | Removed | It stops a run without a window |

The workflow also moves output folders that point outside the job into the job folder.

**Modules that need all image sets in one job.** With `--chunk_size` more than 0, the workflow stops if the
pipeline contains one of these modules (when they are on):

| Module | Condition |
| --- | --- |
| `CorrectIlluminationCalculate` | Set to "All: First cycle" or "All: Across cycles" |
| `LoadData` | Always (each chunk would process the complete CSV file) |
| `Groups` | Grouping is on |
| `TrackObjects`, `MakeProjection`, `CalculateStatistics` | Always |
| `Tile` | Set to tile across cycles |

## The test pipelines

The repository has three small pipelines for the tests:

| File | Use |
| --- | --- |
| `tests/test.cppipe` | One pipeline without illumination (the `test` profile) |
| `tests/test_illum.cppipe` | Illumination pipeline: CorrectIlluminationCalculate of `DNA`, SaveImages `IllumDNA.npy` |
| `tests/test_analysis.cppipe` | Analysis pipeline: CorrectIlluminationApply, Nuclei, Cells, Cytoplasm, and the ExportToSpreadsheet of the PANC1 pipeline (with a prefix, so that the tests check the patch step) |

`tests/test_illum.cppipe` and `tests/test_analysis.cppipe` extract `Well` and `Site` from names such as
`A01_s1_w1.tif`. `tests/test_cellprofiler.py` runs them on two plates.

### `tests/test.cppipe`

| Property | Value |
| --- | --- |
| CellProfiler version | 4.2.8 (`DateRevision: 428`) |
| Input | One grayscale channel, `DNA`. NamesAndTypes matches the images by order. |
| Metadata | None extracted |
| Objects | `Nuclei`, then `Cells` |
| Output modules | `CreateBatchFiles` (the workflow removes it). No ExportToSpreadsheet (the workflow adds it). |

| # | Module | What it does |
| --- | --- | --- |
| 1 | Images | Uses all image files, except files in hidden folders |
| 2 | Metadata | Off (extracts nothing) |
| 3 | NamesAndTypes | Names all images `DNA` |
| 4 | Groups | Off |
| 5 | IdentifyPrimaryObjects | Finds `Nuclei` in `DNA`: diameter 6 to 25 pixels, global Minimum Cross-Entropy threshold, the module discards objects on the border |
| 6 | IdentifySecondaryObjects | Grows `Nuclei` into `Cells` in `DNA` with the Propagation method |
| 7 | MeasureObjectSizeShape | Measures size and shape of `Nuclei` and `Cells`, with Zernike features |
| 8 | MeasureObjectIntensity | Measures the `DNA` intensity of `Nuclei` and `Cells` |
| 9 | CreateBatchFiles | The workflow removes it |

On the 6 test images, this pipeline finds 51 nuclei. `tests/test_cellprofiler.py` checks the number of nuclei
in each image against these reference numbers.
