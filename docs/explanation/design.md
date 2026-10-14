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
| Every image file matches `--group_regex` | Thumbnails or overlays in the image folder would become image sets | `--allow_incomplete_sets` |
| Every image set has the same number of files | A missing channel gives an incomplete image set | `--allow_incomplete_sets` |
| The output and work folders are not in the image folder | A later run would read the results as images | — |
| No module that needs all image sets, when the work is in chunks | Each chunk would calculate its own result, for example its own illumination correction | use `--chunk_size 0` |
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

### When the workflow merges the chunks

| Check | Why |
| --- | --- |
| No two chunks wrote the same mask file | One mask would overwrite the other |
| No site occurs in two chunks (with `--required_metadata`) | The workflow processed the site twice |

## Decisions

**A list of files, not a LoadData CSV.** Each job gives CellProfiler a list of its files. The pipeline finds
its image sets with NamesAndTypes, as in the CellProfiler program. Thus you can use a pipeline from the
program without changes. `--group_regex` makes sure that a chunk always holds complete image sets.

**CellProfiler itself changes the pipeline.** `patch_cppipe.py` uses CellProfiler's own API, not text
search and replace. Thus each change is valid, and CellProfiler checks the new modules. The report lists each
change, and `patched.cppipe` is the pipeline that ran.

**A global image number.** CellProfiler starts `ImageNumber` at 1 in each chunk. The merge adds
`CPNF_GlobalImageNumber`, which is unique in the run, and the same in the image table, the object tables and
the mask list.

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
- GPU plugins (for example Cellpose) are not supported on Berzelius: all jobs run on CPU nodes.
