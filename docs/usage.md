# Run your own images

Use this guide after installing the software and checking the small example.

## Prepare the inputs

Store TIFFs exactly one folder below the image root:

```text
images/
  plate1/
    A02_s1_x0_y0_Fluorescence_405_nm_Ex.tiff
    A02_s1_x0_y0_Fluorescence_488_nm_Ex.tiff
    A02_s1_x0_y0_Fluorescence_561_nm_Ex.tiff
    A02_s1_x0_y0_Fluorescence_638_nm_Ex.tiff
    A02_s1_x0_y0_Fluorescence_730_nm_Ex.tiff
```

These five files form one image set. Every set needs all configured channels.
All images within one plate must have the same width and height.
Do not use RGB images, image stacks, floating-point TIFFs, or deeper subfolders.
The filename must match the pipeline's metadata rule.
Discovery accepts `.tif` and `.tiff`, but the configured filename rule must also accept the extension.
See [file formats](reference/file-formats.md) for the exact rule.

Plate names must start with a letter or digit. Remaining characters may be letters, digits, dots, underscores, or hyphens.
Do not name a plate `logs`, `pipelines`, or `manifests`.
The workflow skips hidden input files. It does not need a metadata spreadsheet.

You must also provide two CellProfiler pipeline files. See [Provide your own pipelines](#provide-your-own-pipelines).
The filename rule of the images must match the pipelines.

## Provide your own pipelines

The workflow does not create pipelines. You provide the two CellProfiler pipeline files.

!!! important "The files in `cp-configs/` are examples"
    The supplied files fit one screen. That screen has five channels (DNA, RNA, AGP, Mito, ER) and its own file names.
    They may not fit your channels, your file names or your objects. Make your own files for your images.

The configuration folder must contain exactly these two `.cppipe` files:

- `1_illumination.cppipe`: calculates the illumination correction of each plate
- `2_analysis.cppipe`: applies the correction, finds the cells and measures them

The workflow stops with an error if the folder has other `.cppipe` files or if one of the two names is missing.
Use CellProfiler 4.2.8.1 to make and save the files. Keep the filename and channel rules the same in both pipelines.
Before the first job starts, PREPARE checks the pipelines. The rules are on the page [Change a CellProfiler pipeline](how-to/modify-pipeline.md).
Test your pipelines on a few image sets before you run a full screen.

Give the folder with `--configs <folder>`. On Berzelius, see [Before you start](how-to/run-on-hpc.md#before-you-start).

## Start a local run

This is an unexecuted recipe for your data. Replace `images` with your image folder.
Activate `cp-headless` first and run from the repository root.

```bash
nextflow run . -profile local \
  --images images --configs cp-configs \
  --outdir results --project screen01 \
  --nf_work_dir work-screen01
```

Expected results go to `results/projects/screen01/`.
If another session owns that project name, Nextflow warns and uses its session ID instead.
Always use the output path printed at startup.
Keep results and work folders outside the image input folder.

| Profile | Execution | Environment |
|---|---|---|
| `local` | Runs jobs on this machine within the shared CPU and memory budget | Activated `cp-headless` |
| `berzelius` | Submits jobs to Slurm | Activated environment accessible on compute nodes |

Always select a profile. Without one, profile-specific resource limits, reports, and retries do not apply.
Use single-dash Nextflow options such as `-profile` and `-resume`.
Use double-dash workflow parameters such as `--images` and `--batch_size`.
All workflow parameters appear in the [generated reference](reference/parameters.md).

## Resume a run

Keep `.nextflow/`, the work directory, inputs, code, and original output folder.
Resume from the same launch directory with the same active environment.

The startup message includes the session ID, inputs, and output path.
It omits the profile, resource overrides, batch size, and custom work directory.
Add those original options when resuming.

Template only: replace `SESSION_ID` with the ID from `run.json`.

```bash
nextflow run . -profile local \
  --images images --configs cp-configs \
  --outdir results --project screen01 \
  --nf_work_dir work-screen01 \
  -resume SESSION_ID
```

Nextflow can reuse valid cached tasks when their inputs and settings still match.
Missing work outputs or changed inputs can cause tasks to run again.
The final table is moved out of its task folder, so CONCAT may run again on resume.
Neither profile deletes work files automatically.
Only remove a run's work data after checking and archiving results, when you no longer need resume.

With `--project`, both profiles write `trace.txt`, `report.html`, and `timeline.html` to `report/` in the project folder.
Without `--project`, they overwrite these files in the launch folder. Avoid concurrent runs from the same launch folder.
For cluster use, see [run on Berzelius](how-to/run-on-hpc.md).
