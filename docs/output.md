# Output

This page describes each folder in `--outdir`: what it contains, which step makes it, and how to use it.
The exact columns and fields of each file are in [File formats](reference/file-formats.md).

```text
results/
├── features/              merged tables, mask_manifest.csv, merge_report.json
├── masks/                 one mask per image set and object type
├── cellprofiler_outputs/  other files that your own pipeline saves
├── pipeline/              patched.cppipe, patch_report.json
├── logs/                  the CellProfiler log and the checks of each chunk
└── pipeline_info/         run_info.json and the Nextflow reports
```

By default, the workflow copies the results into `--outdir` (`--publish_mode copy`). Thus you can remove the
`work/` folder after the run.

## features/

**Made by:** MERGE_FEATURES, after all chunks. **Use it for:** profiling (for example with
[CytoTable](https://github.com/cytomining/CytoTable) and [pycytominer](https://github.com/cytomining/pycytominer)).

| File | Content |
| --- | --- |
| `<prefix>Image.csv` | One row per image set: counts, image measurements, metadata, file names |
| `<prefix><Object>.csv` | One row per object, for example `MyExpt_Nuclei.csv` |
| `<prefix>Experiment.csv` | Information about the CellProfiler run |
| `mask_manifest.csv` | One row per image set and object type: the mask path and the input images |
| `merge_report.json` | The number of chunks and image sets, and the size of each table |

The names come from the ExportToSpreadsheet module of your pipeline. `MyExpt_` is its default prefix.
Each table starts with two columns that the workflow adds:

- `CPNF_Chunk`: the chunk of the row, for example `chunk_0003`.
- `CPNF_GlobalImageNumber`: an image number that is unique in the complete run.

CellProfiler starts `ImageNumber` at 1 in each chunk. Thus join the image table, the object tables and the
mask list on `CPNF_GlobalImageNumber`, never on `ImageNumber` alone. With `--gzip_features true`, the files
end in `.csv.gz`.

## masks/

**Made by:** CELLPROFILER (mask writers that the workflow adds to your pipeline). **Use it for:** checking
the segmentation, training models, or measuring objects again.

The folder has the same sub-folders as the image folder. The workflow names each mask after the first input
image of its image set, plus `_<Object>_mask`:

```text
masks/plate1/site0_DNA_Nuclei_mask.tiff
masks/plate1/site0_DNA_Cells_mask.tiff
```

A mask is a 16-bit image (`.tiff` by default, see `--mask_format`). The value 0 is the background. The values
1, 2, 3, ... are the objects. The value of an object is its `ObjectNumber` in the object table. Use
`mask_manifest.csv` to find the mask of an image set.

## cellprofiler_outputs/

**Made by:** CELLPROFILER. Files that your own pipeline saves (for example overlays or cropped objects),
in one sub-folder per chunk. The folder is empty if your pipeline saves no other files.

## pipeline/

**Made by:** PATCH_PIPELINE, once per run.

- `patched.cppipe`: the pipeline that CellProfiler ran. Open it in CellProfiler to see the changes.
- `patch_report.json`: each change that the workflow made. It also gives the CellProfiler version, the object
  types, and the modules that need all image sets in one job (`chunk_unsafe_modules`).

## logs/

**Made by:** CELLPROFILER, one pair of files per chunk.

- `log_<chunk>.txt`: the complete CellProfiler log.
- `qc_<chunk>.json`: the results of the checks. It gives the number of image sets and masks, and the
  expected numbers. It also gives the number of images without objects, and the warnings and errors.

## pipeline_info/

**Made by:** Nextflow and the workflow.

- `run_info.json`: the git commit, the Nextflow version, the container and all parameters. Keep it with the
  results: it shows how the workflow made them.
- `report.html`, `timeline.html`: Nextflow reports. Open them in a web browser.
- `trace.txt`: the time and memory of each job. Use it to choose the memory and the chunk size.
