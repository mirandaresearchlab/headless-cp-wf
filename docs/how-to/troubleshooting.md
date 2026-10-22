# Troubleshooting

This page tells you how to find the cause of an error and fix it. Find the message in the tables below.

## Errors before CellProfiler starts

| Message | Cause and solution |
| --- | --- |
| `image set(s) do not have N file(s)` | A channel is missing, or extra files are in the image folder. Check the examples in the message. See [Group the files of one site](../usage.md#group-the-files-of-one-site). |
| `file(s) do not match --group_regex` | Thumbnails or other files are in the image folder, or the pattern is too narrow. |
| `--outdir ... is inside --input_dir` | Choose an output folder outside the image folder. |
| `must process all image sets in one CellProfiler run` | The analysis pipeline has a module that needs all images, usually CorrectIlluminationCalculate. Move it to the illumination pipeline (`--illum_pipeline`), or use `--chunk_size 0`. |
| `has no plate: put the images of each plate into their own folder` | A file is directly in `--input_dir`. Move the images into one folder per plate, or set `--plate_regex`. |
| `plate name '...' may only have letters, digits` | Rename the plate folder: no spaces or special characters. |
| `--segmentation_cpus N is more than --total_cpus M` | Raise `--total_cpus`, or lower `--segmentation_cpus`. |
| `uses the plugin module RunCellpose, but ... has no runcellpose.py` | Set `--plugins_dir` to a folder with the plugin, or use the default `cp-plugins/`. |
| `uses RunCellpose, but --container ... has no Cellpose` | Set `--container` to the Cellpose image (`containers/cellprofiler-cellpose`). |
| `has no CorrectIlluminationCalculate module` / `has no SaveImages module that saves an image as .npy` | The file of `--illum_pipeline` is not an illumination pipeline. |
| `--illum_dir ...: no .npy files for plate` / `expected N (one per channel)` | The folder of `--illum_dir` lacks the functions of a plate. Give the output folder of a run that had the same plates. |
| `--<name> must be true or false` | Give boolean parameters as `true` or `false`. |
| `CellProfiler reported errors while loading the pipeline` | A plugin is missing (`--plugins_dir`), or the pipeline comes from a newer CellProfiler (`--container`). |
| `Process requirement exceeds available memory` | Set `--max_memory` and `--max_cpus` to the size of your computer. |
| `Cannot find Java or it's a wrong version` | Nextflow needs Java 17 to 26. Run the lines of [Installation, step 5](../getting-started/installation.md#step-5-activate-nextflow). |
| `docker: command not found` in `.command.run` (exit status 127) | You used `-profile docker`, but Docker is not installed. Install and start it ([Run with Docker](run-with-docker.md)), or use `-profile local` ([Run without Docker](run-without-docker.md)). |
| `Cannot connect to the Docker daemon` | The Docker service does not run. In a lab workstation, run `bash scripts/start-docker-in-container.sh` ([Run with Docker](run-with-docker.md#step-2-start-docker)). |
| `Command 'ps' required by nextflow to collect task metrics cannot be found` | The computer has no `ps`, for example in a minimal container. Install the package `procps`. |
| `Could not import CellProfiler (No module named 'cellprofiler_core')` | With `-profile local`: the jobs use a Python without CellProfiler. Put the `bin` folder of the CellProfiler environment first in `PATH`. See [Run without Docker](run-without-docker.md). |
| `Error finding javahome on linux: ['bash', '-c', 'type -p java']` | CellProfiler cannot find `java`. With the `local` profile, put the `bin` folder of the CellProfiler environment first in `PATH`. See [Run without Docker](run-without-docker.md). |
| `nextflow: command not found` | Run the lines of [Installation, step 5](../getting-started/installation.md#step-5-activate-nextflow). On Berzelius, `source` your settings file. |

## Errors after a CellProfiler job

| Message | Cause and solution |
| --- | --- |
| `CellProfiler processed N image sets but the workflow predicted M` | `--group_regex` does not group the files as NamesAndTypes in your pipeline does. |
| `required by --required_metadata` | The Metadata module of your pipeline does not make this value. Check its regular expression. |
| `counts N objects but ... has M rows` | The export of CellProfiler is not complete. Look at the log of the chunk. |
| `Per-image table is empty` | The filters in the Images or NamesAndTypes module exclude all files. Compare them with your file names and `--extensions`. |
| `trying to overwrite ... in headless mode` | Your own SaveImages gives two image sets the same file name. Turn on "Create subfolders" in that module, or rename the input files. |
| `Missing 'Nuclei' mask for ImageNumber ...` | A mask was not saved. Look at the log of the chunk for the error of SaveImages. |
| `metadata=IllumDNA: Missing from channel` (CellProfiler log) | The chunk got no illumination function, or NamesAndTypes does not find it. Check the rule of the function in NamesAndTypes (for example "file startswith IllumDNA"), and `qc_illum_<plate>.json`. |
| `found N illumination function(s) (.npy), expected M` | The illumination pipeline saved fewer functions than it has SaveImages modules. Look at `log_illum_<plate>.txt`. |
| `minimum ... is not > 0` / `value(s) are not finite` | An illumination function is not usable. Check the images of the plate and the settings of CorrectIlluminationCalculate. |
| `rows have Metadata_Plate other than` | Your Metadata module extracts a plate name that differs from the plate folder. Remove the plate from the Metadata module, or rename the folders. |
| `input file(s) are not readable` | The container cannot see the images. Check the mounts and the file permissions. |
| `AttributeError: 'str' object has no attribute ...` in `check_chunk.py` | A helper script uses a Python feature that is newer than 3.8. See [Contributing](../about/contributing.md). |

## Errors of the merge

| Message | Cause and solution |
| --- | --- |
| `the merged tables lack [...]` | The pipeline exports no Cells, Nuclei or Cytoplasm table. Check ExportToSpreadsheet and the object names, or set `--check_compartments false`. |
| `... has no column(s) ['Metadata_Well', ...]` | The Metadata module does not extract Well or Site. |
| `... has no column(s) ['Parent_Nuclei']` | `Cytoplasm.csv` must come from IdentifyTertiaryObjects (Cells minus Nuclei). |
| `image set {...} appears in ... and in ...` | The same plate, well and site occur twice. Check the file names and the Metadata regular expression. |
| `rows have no Metadata_Plate` | A table has rows without a plate. Look at `qc_<chunk>.json` of the chunks. |

## Other problems

| Problem | Cause and solution |
| --- | --- |
| Docker: `cellprofiler: unrecognized arguments ... bash` | Use the `docker` profile. It removes the entry point of the image. |
| Very slow in containers | Keep the thread settings of the workflow. They limit the threads of each job to its CPU cores. |
| Jobs stop with exit code 137 or 140 | Not enough memory (137) or time (140). The workflow tries again with more, up to `--max_memory` and `--max_time`. |

## Look at a failed job

Nextflow prints the work folder of a failed job, for example `work/a6/dca722...`. In that folder:

| File | Content |
| --- | --- |
| `.command.sh` | The script of the job |
| `.command.err`, `.command.log` | The messages of the job |
| `.exitcode` | The exit code |
| `log_<chunk>.txt`, `log_illum_<plate>.txt` | The CellProfiler log (CELLPROFILER and ILLUM jobs) |
| `qc_<chunk>.json`, `qc_illum_<plate>.json` | The results of the checks (CELLPROFILER and ILLUM jobs) |

To run the job again by hand, go to the folder and run `bash .command.run`.
