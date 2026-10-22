# Data checks and design

This page explains the main design decisions of the workflow, and the checks that protect your data. The steps
themselves are in [How the workflow works](workflow.md).

## Stop, do not guess

The results of the workflow are the input for profiling. A missing channel, a duplicated site or a lost mask
does not cause an error later. It gives wrong biology without any message. Thus the workflow stops with a
clear message when a check fails, and shows examples. Some checks have an option to continue with a warning,
for data that you know is imperfect.

## The checks

### Before CellProfiler starts

| Check | Why | Option |
| --- | --- | --- |
| Every file has a plate (a plate folder, or `--plate_regex`), with a safe name | The plate becomes a folder name and `Metadata_Plate` | — |
| Every image file matches `--group_regex` (per plate) | Thumbnails or overlays in the image folder would become image sets | `--allow_incomplete_sets` |
| Every image set of a plate has the same number of files | A missing channel gives an incomplete image set | `--allow_incomplete_sets` |
| The output and work folders are not in the image folder | A later run would read the results as images | — |
| No module that needs all image sets in the analysis pipeline, when the work is in chunks | Each chunk would calculate its own result, for example its own illumination correction | move it to `--illum_pipeline`, or `--chunk_size 0` |
| The illumination pipeline calculates and saves `.npy` functions at the last cycle | Otherwise the chunks have no functions to apply | — |
| `--segmentation_cpus` is not more than `--total_cpus` and `--max_cpus` | No chunk could start | — |
| A pipeline with plugins finds them in `--plugins_dir`; RunCellpose does not run in the official image | The jobs would fail later | — |
| Boolean parameters are `true` or `false` | Nextflow passes `--flag false` as the text "false", which would count as true | — |
| Berzelius: an account, a CPU partition, and no folders in `$HOME` | GPU hours are expensive, and `$HOME` is small | — |

### After each CellProfiler job

| Check | Why | Option |
| --- | --- | --- |
| No module errors in the log, and an image table that is not empty | CellProfiler can end with exit code 0 after errors | — |
| The number of image sets is the predicted number | Otherwise the channels of a site were split between chunks | `--strict_image_count false` |
| `Count_<Object>` agrees with the rows of the object table | Otherwise the export is incomplete | — |
| One mask per image set and object type, never shared | Otherwise a mask is missing or lost | — |
| Required metadata is present, non-empty and unique | Joins on plate, well and site would be wrong | only with `--required_metadata` |
| `Metadata_Plate` of every row is the plate of the chunk | A pipeline that extracts another plate name would mix plates | — |

### After each ILLUM job

| Check | Why |
| --- | --- |
| One `.npy` file per SaveImages module of the illumination pipeline | A missing function would leave a channel uncorrected |
| All values finite and greater than 0 | Dividing by 0, NaN or a negative value gives wrong intensities |

### When the workflow merges the chunks

| Check | Why |
| --- | --- |
| No two chunks wrote the same mask file | One mask would overwrite the other |
| No site occurs twice (with `--required_metadata`, or plate, well and site with `--check_compartments`) | The workflow processed the site twice |
| Every row of an image or object table has a plate | Profiles of different plates would mix |
| With `--check_compartments`: the compartment tables and their join columns exist (`Image`, `Cells`, `Nuclei`, `Cytoplasm`; `Parent_Cells`, `Parent_Nuclei`; plate, well, site) | A join of the compartments of each cell would fail, or join cells to the wrong images |

## Decisions

**A list of files, not a LoadData CSV.** Each job gives CellProfiler a list of its files. The pipeline finds
its image sets with NamesAndTypes, as in the CellProfiler program. Thus you can use a pipeline from the
program without changes. `--group_regex` makes sure that a chunk always holds complete image sets.

**CellProfiler itself changes the pipeline.** `patch_cppipe.py` uses CellProfiler's own API, not text
search and replace. Thus each change is valid, and CellProfiler checks the new modules. The report lists each
change, and `patched.cppipe` is the pipeline that ran.

**One illumination job per plate, and chunks per plate.** An illumination function is the average of all
images of a plate, so it can not be cut into chunks. The analysis can. Each chunk gets only the functions of
its own plate (the workflow joins them by the plate name), and a chunk never holds sites of two plates.

**A global image number.** CellProfiler starts `ImageNumber` at 1 in each chunk. The merge rewrites
`ImageNumber`, so that it is unique over all plates and chunks, and the same in the image table, the object
tables and the mask list. Joins of the tables use it. `CPNF_ChunkImageNumber` keeps the original value.

**The merged tables are the end.** The workflow makes the tables of all plates, ready to be joined into one row
per cell, but it does not make single-cell profiles itself. That step comes after the workflow.

**Pinned software.** The workflow pins the CellProfiler container by its digest. `run_info.json` records the code
version, the container and all parameters of each run. Thus you can find out later how the workflow made the results.

**Same results as the first version.** The tests compare the number of nuclei in each test image with the
numbers from the first version of the workflow. A different number means a change in the biological results.

## Limitations

- The workflow names each mask after the first input image of its image set. Some files (`.nd2`, `.czi`) hold
  many sites in one file. Then several image sets get the same mask name, and the run stops. For such files,
  save masks with names from metadata in your own pipeline.
- Each job links the complete image folder. This is fast on local disks and on shared cluster storage. On cloud
  storage, each chunk copies the folder.
- We tested the workflow with CellProfiler 4.2.8. CellProfiler 5 changes some modules. If you change the
  version, read `patch_report.json`.
- Cellpose runs on CPUs: all jobs run on Berzelius CPU nodes, and the workflow sets RunCellpose to "Use GPU:
  No". A GPU version (Cellpose-SAM) would need a GPU process of its own.
- Cytoplasm objects without a parent cell or nucleus (`Parent_Cells` = 0) and cells without cytoplasm can not
  be joined into one row per cell. The merge does not count them: check them before you make profiles.
