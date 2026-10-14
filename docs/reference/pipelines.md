# CellProfiler pipelines

This page lists what the workflow needs from a CellProfiler pipeline, and describes the test pipeline of the
repository. How to use your own pipeline: [Change the CellProfiler pipeline](../how-to/change-pipeline.md).

## Requirements for your pipeline

| Requirement | Why |
| --- | --- |
| Made in CellProfiler 4.2.8 (`DateRevision: 428`), or set `--container` to its version | A pipeline from a newer version can fail to load, or give different results |
| Finds its images with Images, Metadata and NamesAndTypes | The workflow gives each job a list of files (`--file-list`) |
| NamesAndTypes groups the files as `--group_regex` does | Otherwise the image-set count check stops the run |
| With `--chunk_size` more than 0: no module that needs all image sets | See the list below |
| Plugins in `--plugins_dir` | CellProfiler must find them in each job |

You do not need to add mask saving or ExportToSpreadsheet: the workflow adds them. It also removes
CreateBatchFiles, and it moves output folders that point outside the job.

**Modules that need all image sets in one job.** With `--chunk_size` more than 0, the workflow stops if the
pipeline contains one of these modules (when they are on):

| Module | Condition |
| --- | --- |
| `CorrectIlluminationCalculate` | Set to "All: First cycle" or "All: Across cycles" |
| `LoadData` | Always (each chunk would process the complete CSV file) |
| `Groups` | Grouping is on |
| `TrackObjects`, `MakeProjection`, `CalculateStatistics` | Always |
| `Tile` | Set to tile across cycles |

## The test pipeline: `tests/test.cppipe`

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
