# Read results and check completion

Use this page to locate the outputs and connect each cell row to its mask.

The output root is `<outdir>/projects/<project>/`.
Without a project name, the session ID becomes the folder name.
A project name already owned by another session also falls back to the session ID.

## Files in the output folder

| Path relative to the output root | Producer | Content |
|---|---|---|
| `run.json` | Workflow startup | Session ID, project name, input paths, Nextflow version, launch command |
| `illum/<plate>/Illum*.npy` | ILLUMINATION | One correction array per channel |
| `illum/<plate>/provenance.json` | ILLUMINATION | Plate identity and SHA-256 correction checksums |
| `masks/<plate>/*.tiff` | ANALYSIS | Unsigned 32-bit object label masks. With RunCellpose, they include the Cellpose objects, equal to the SEGMENT masks |
| `masks/<plate>/<batch>/` | SEGMENT | Only with `--segmentation_only`: the Cellpose-SAM masks of one batch (`masks/*.tiff`), `mask_manifest.csv` and `validation.json`. See [segment only](usage.md#segment-only) |
| `cp_features/<plate>.parquet` | MERGE | Per-cell measurements of one plate, as Parquet. All plates have the same columns and types |
| `logs/run_inputs/samplesheet.csv` | PREPARE | One row per image file: metadata, channel, and path. Use it as `--input` for a new run |
| `logs/run_inputs/plan.json` | PREPARE | Plates, source files, manifests, and batch sizes |
| `logs/run_inputs/manifests/<plate>/*.csv` | PREPARE | Complete plate and batch image lists |
| `logs/run_inputs/pipelines/*.cppipe` | PREPARE | Working pipeline copies |
| `logs/run_inputs/pipelines/contract.json` | PREPARE | Channels, objects, versions, input file sizes/times, and pipeline checksums |
| `logs/<plate>/illumination.*` | ILLUMINATION | Log, metrics JSON, and LoadData CSV |
| `logs/<plate>/batch_*.log` | ANALYSIS | CellProfiler task logs |
| `logs/<plate>/batch_*.metrics.json` | ANALYSIS | Task timing and resource measurements |
| `logs/<plate>/batch_*.load_data.csv` | ANALYSIS | Exact image and correction file paths used |
| `logs/<plate>/batch_*.validation.json` | ANALYSIS | Validation results and measurement repairs |
| `logs/<plate>/segment_*.metrics.json` | SEGMENT | Only with RunCellpose: device, workers, time, image sets per minute and, on a GPU, mean GPU use and peak GPU memory |
| `logs/<plate>/segment_*.gpu.csv` | SEGMENT | Only with `--segmentation gpu`: GPU use and memory for each second of the task |
| `logs/<plate>/segment_*.worker*.log` | SEGMENT | CellProfiler log of each worker |
| `logs/<plate>/segment_*.validation.json` | SEGMENT | Batches, number of masks, and the checked illumination files |
| `logs/<plate>/merge.json` | MERGE | Per-plate merge summary. `objects` is the sum of `Count_<Object>` for cells, cytoplasm and nuclei: each object is in the table once, or is counted as not joined. `bytes` is the size of the Parquet file |
| `logs/status-*.json` | Workflow completion | Success flag, exit status, duration, session, command, error |
| `logs/nextflow-*.log` | Workflow completion | Saved copy of the launch log when available |

With `--project`, Nextflow writes `report/report.html`, `report/timeline.html`, and `report/trace.txt` in the project folder.
Without `--project`, it writes them in the launch folder, because the session ID is not known when the profile loads.
The HTML report summarizes task resources. The timeline shows when tasks ran.
The launch folder keeps `.nextflow.log`.
Early startup failures may not produce project outputs. Use `.nextflow.log` in that case.

Batch tables and mask manifests remain in the work directory.
The per-plate Parquet tables are copied to `cp_features/` and also stay in the work directory, so `-resume` does not merge again. Both profiles preserve work files.

## Check the run before using the data

1. Confirm that Nextflow finished successfully.
2. Read the newest status file and check `success` is true.
3. Check that `cp_features/` has one `<plate>.parquet` per plate and the merge summaries cover your plates.
4. Review batch validation reports and inspect representative masks over the raw images.

Partial outputs can exist after a failure. Passing file checks does not prove biological accuracy.

## Interpret the per-cell table

| Columns | Meaning |
|---|---|
| `Metadata_Plate`, `Metadata_Well`, `Metadata_Site`, `Metadata_X`, `Metadata_Y` | Image identity |
| `Metadata_Acquisition` | Shared filename prefix, such as `A02_s1_x0_y0` |
| `Metadata_Batch`, `Metadata_ImageNumber` | Batch identity and batch-local image number |
| `Metadata_PlateImageNumber` | Image position in the plate, sorted by well, then site, then other metadata (numbers as numbers) |
| `Metadata_ObjectNumber` | Cell label in the Cells mask |
| `Cells_*`, `Cytoplasm_*`, `Nuclei_*` | Measurements from those cell compartments |
| `Image_*` | Whole-image measurements repeated for each cell row |

Each file holds one plate. Rows follow plate image order, then cell number.
The types are fixed by the column name, so they are the same for every plate:

| Columns | Type |
|---|---|
| `Metadata_PlateImageNumber`, `Metadata_ImageNumber`, `Metadata_ObjectNumber`, `Metadata_Site`, `Metadata_X`, `Metadata_Y` | 64-bit integer |
| Other `Metadata_*`, `Image_FileName_*`, `Image_PathName_*`, `Image_URL_*`, `Image_MD5Digest_*` | Text |
| All other columns (measurements) | 64-bit float |

CellProfiler writes its values as text. MERGE parses each value once into its type, without rounding.
An image with no cells contributes no cell rows. Use manifests and reports to check image coverage.
Nuclei join through their parent-cell relationships, not by assuming matching label numbers.
Missing values are nulls: blank fields (for example a cell without a nucleus), and `nan` and `inf` from CellProfiler.
Do not replace nulls with zero without deciding what that means for your analysis.

Read only the columns you need, for example `pandas.read_parquet(path, columns=[...])`.
To read all plates as one table, give the `cp_features/` folder instead of one file:
`pandas.read_parquet('cp_features')`, `polars.scan_parquet('cp_features/*.parquet')` or
`duckdb.sql("SELECT ... FROM 'cp_features/*.parquet'")`.
See the [tested reading pattern](tutorials/first-run.md#5-read-a-few-cell-identifiers).

## Match a row to a mask

Use this relative path:

```text
masks/<Metadata_Plate>/<Metadata_Acquisition>_Cells.tiff
```

Pixel value zero means background. Pixels equal to `Metadata_ObjectNumber` belong to that cell.
Object numbers are local to an image and object type. They are not global cell identifiers.
The TIFF description contains JSON metadata, source files, and pipeline steps.
The default pipeline saves Cells, CellsPaired, Cytoplasm, Nuclei, and NucleiPaired masks.
In `cp-configs-cellpose/`, NucleiPaired is the Cellpose-SAM mask. Its provenance names LoadLabelMasks and the DNA image.

## Checks performed by the software

Analysis checks the exact image sets, module errors, mask types, mask provenance, counts, labels, and measured areas.
It checks that each object's measured area equals its mask pixel count.
Merge rejects missing or unvalidated batches, mismatched columns, inconsistent parent links, and repeated image sets.
It also rejects a nucleus or cytoplasm whose cell does not exist, so no object is dropped without a report.
With RunCellpose, SEGMENT and ANALYSIS check that each mask belongs to its image set. See [segmentation choices](explanation/segmentation.md#how-the-masks-stay-linked-to-their-images).
After the Parquet file is written, MERGE reads it back. It stops if the columns differ from the merged header, the row count differs from the cells in `merge.json`, a row breaks the order (plate image, cell), or the `Cells_ObjectNumber`, `Cytoplasm_ObjectNumber`, `Cytoplasm_Parent_Cells` or `Nuclei_Parent_Cells` of a row points to another cell.
A value that is not a number in a measurement column also stops MERGE.
See [troubleshooting](how-to/troubleshooting.md) if any check fails.
