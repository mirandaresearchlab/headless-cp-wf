# Output

This page describes each folder in `--outdir`: what it contains, which step makes it, and how to use it.
The exact columns and fields of each file are in [File formats](reference/file-formats.md).

```text
results/
├── cellprofiler_tables/   Image.csv  Cells.csv  Nuclei.csv  Cytoplasm.csv  Experiment.csv  (all plates)
│                          mask_manifest.csv  merge_report.json
├── PANC1_P01/             illum/  masks/  (cellprofiler_outputs/)
├── PANC1_P02/             illum/  masks/
├── pipeline/              patched.cppipe, patch_report.json (and illum_* for the illumination pipeline)
├── logs/                  the CellProfiler log and the checks of each ILLUM job and each chunk
└── pipeline_info/         run_info.json and the Nextflow reports
```

By default, the workflow copies the results into `--outdir` (`--publish_mode copy`). Thus you can remove the
`work/` folder after the run.

## cellprofiler_tables/

**Made by:** MERGE_FEATURES, once after all chunks of all plates. **Use it for:** your own analysis, or as the
input of a tool that joins the compartments of each cell into one row per cell (a single-cell profile).

| File | Content |
| --- | --- |
| `Image.csv` | One row per image set (site): counts, image measurements, metadata, file names |
| `Cells.csv`, `Nuclei.csv`, `Cytoplasm.csv` | One row per object. The names are the object names of your pipeline. |
| `Experiment.csv` | Information about the CellProfiler run (one copy per chunk) |
| `mask_manifest.csv` | One row per image set and object type: the mask path and the input images |
| `merge_report.json` | The number of chunks and image sets, and the size of each table |

The tables have no file name prefix: the workflow removes the prefix of ExportToSpreadsheet, so that the names
are the same in every run (`Image.csv`, `Cells.csv`, `Nuclei.csv`, `Cytoplasm.csv`). Each table with image
sets starts with two columns that the workflow adds:

- `CPNF_Chunk`: the chunk of the row, for example `PANC1_P01_chunk_0003`.
- `CPNF_ChunkImageNumber`: the `ImageNumber` that CellProfiler wrote in that chunk.

CellProfiler starts `ImageNumber` at 1 in each chunk. The merge rewrites `ImageNumber` so that it is unique
over all plates and chunks, with the same value in the image table, the object tables and the mask list. Thus
you can join the tables on `ImageNumber` (and `ObjectNumber`). Every row also has `Metadata_Plate`: the
workflow adds it from the plate folder. `Metadata_Well` and `Metadata_Site` come from the Metadata module of
your pipeline.

**Join the compartments of a cell.** With `--check_compartments true` (the default), the merge checks that
the tables can be joined into one row per cell, and stops if they cannot:

- `Cytoplasm.csv` has `Parent_Cells` and `Parent_Nuclei`: the `ObjectNumber` of its cell in `Cells.csv` and
  of its nucleus in `Nuclei.csv`, in the same image (`ImageNumber`).
- Every image and object table has `ImageNumber`, `Metadata_Plate`, `Metadata_Well` and `Metadata_Site`; every
  object table has `ObjectNumber` and `Number_Object_Number`.
- No plate, well and site occur twice.

IdentifyTertiaryObjects can write cytoplasm objects with `Parent_Cells` = 0 (for example a cell without pixels
outside its nucleus). Such an object has no cell to join with.

With `--merge_all_plates false`, each plate gets its own tables in `<plate>/cellprofiler_tables/` instead.

## `<plate>/illum/`

**Made by:** ILLUM, one job per plate. The illumination functions of the plate (`.npy`, one per channel). The
analysis chunks of the plate divided each image by them. The workflow checked that each function exists, is
finite and is greater than 0 (see `logs/qc_illum_<plate>.json`). Give this folder to a later run with
`--illum_dir results` to use the same functions again.

## `<plate>/masks/`

**Made by:** CELLPROFILER (mask writers that the workflow adds to your pipeline). **Use it for:** checking
the segmentation, training models, or measuring objects again.

The workflow names each mask after the first input image of its image set, plus `_<Object>_mask`. Sub-folders
below the plate folder stay the same:

```text
PANC1_P01/masks/A02_s1_x0_y0_Fluorescence_561_nm_Ex_Nuclei_mask.tiff
PANC1_P01/masks/A02_s1_x0_y0_Fluorescence_561_nm_Ex_Cells_mask.tiff
PANC1_P01/masks/A02_s1_x0_y0_Fluorescence_561_nm_Ex_Cytoplasm_mask.tiff
```

A mask is a 16-bit image (`.tiff` by default, see `--mask_format`). The value 0 is the background. The values
1, 2, 3, ... are the objects. The value of an object is its `ObjectNumber` in the object table. Use
`mask_manifest.csv` to find the mask of an image set: `MaskPath` is relative to `--outdir`.

## `<plate>/cellprofiler_outputs/`

**Made by:** CELLPROFILER. Files that your own pipeline saves (for example overlays or cropped objects),
in one sub-folder per chunk. The folder is missing if your pipeline saves no other files.

## pipeline/

**Made by:** PATCH_PIPELINE, once per pipeline.

- `patched.cppipe`: the analysis pipeline that CellProfiler ran. Open it in CellProfiler to see the changes.
- `patch_report.json`: each change that the workflow made. It also gives the CellProfiler version, the object
  types, and the modules that need all image sets in one job (`chunk_unsafe_modules`).
- `illum_patched.cppipe`, `illum_patch_report.json`: the same for the illumination pipeline. The report lists
  the functions that it saves (`illum_outputs`).

## logs/

**Made by:** ILLUM and CELLPROFILER.

- `log_<chunk>.txt`, `log_illum_<plate>.txt`: the complete CellProfiler log of each job.
- `qc_<chunk>.json`: the results of the checks of a chunk. It gives the plate, the number of image sets and
  masks, and the expected numbers. It also gives the number of images without objects, and the warnings and
  errors.
- `qc_illum_<plate>.json`: the shape, minimum, maximum and mean of each illumination function of the plate.

## pipeline_info/

**Made by:** Nextflow and the workflow.

- `run_info.json`: the git commit, the Nextflow version, the containers, all parameters, and the plates with
  their sites and chunks. Keep it with the results: it shows how the workflow made them.
- `report.html`, `timeline.html`: Nextflow reports. Open them in a web browser.
- `trace.txt`: the cores, the memory, the time and the peak memory (`peak_rss`) of each job. Use it to choose
  the memory and the chunk size.
