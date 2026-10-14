# Troubleshooting

This page tells you how to find the cause of an error and fix it. Find the message in the tables below.

## Errors before CellProfiler starts

| Message | Cause and solution |
| --- | --- |
| `image set(s) do not have N file(s)` | A channel is missing, or extra files are in the image folder. Check the examples in the message. See [Group the files of one site](../usage.md#group-the-files-of-one-site). |
| `file(s) do not match --group_regex` | Thumbnails or other files are in the image folder, or the pattern is too narrow. |
| `--outdir ... is inside --input_dir` | Choose an output folder outside the image folder. |
| `must process all image sets in one CellProfiler run` | The pipeline has a module that needs all images. Use `--chunk_size 0`. |
| `--<name> must be true or false` | Give boolean parameters as `true` or `false`. |
| `CellProfiler reported errors while loading the pipeline` | A plugin is missing (`--plugins_dir`), or the pipeline comes from a newer CellProfiler (`--container`). |
| `Process requirement exceeds available memory` | Set `--max_memory` and `--max_cpus` to the size of your computer. |
| `Cannot find Java or it's a wrong version` | Nextflow needs Java 17 to 26. Set `JAVA_HOME` to a supported Java. |
| `nextflow: command not found` | Activate the development environment (`source .venv/bin/activate`), or install Nextflow. |

## Errors after a CellProfiler job

| Message | Cause and solution |
| --- | --- |
| `CellProfiler processed N image sets but the workflow predicted M` | `--group_regex` does not group the files as NamesAndTypes in your pipeline does. |
| `required by --required_metadata` | The Metadata module of your pipeline does not make this value. Check its regular expression. |
| `counts N objects but ... has M rows` | The export of CellProfiler is not complete. Look at the log of the chunk. |
| `Per-image table is empty` | The filters in the Images or NamesAndTypes module exclude all files. Compare them with your file names and `--extensions`. |
| `trying to overwrite ... in headless mode` | Your own SaveImages gives two image sets the same file name. Turn on "Create subfolders" in that module, or rename the input files. |
| `Missing 'Nuclei' mask for ImageNumber ...` | A mask was not saved. Look at the log of the chunk for the error of SaveImages. |
| `input file(s) are not readable` | The container cannot see the images. Check the mounts and the file permissions. |
| `AttributeError: 'str' object has no attribute ...` in `check_chunk.py` | A helper script uses a Python feature that is newer than 3.8. See [Contributing](../about/contributing.md). |

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
| `log_<chunk>.txt` | The CellProfiler log (CELLPROFILER jobs) |
| `qc_<chunk>.json` | The results of the checks (CELLPROFILER jobs) |

To run the job again by hand, go to the folder and run `bash .command.run`.
