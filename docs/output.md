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
| `masks/<plate>/*.tiff` | ANALYSIS | Unsigned 32-bit object label masks |
| `cp_features/all_plates.csv.gz` | CONCAT | Combined per-cell measurements, compressed with gzip |
| `logs/run_inputs/plan.json` | PREPARE | Plates, source files, manifests, and batch sizes |
| `logs/run_inputs/manifests/<plate>/*.csv` | PREPARE | Complete plate and batch image lists |
| `logs/run_inputs/pipelines/*.cppipe` | PREPARE | Working pipeline copies |
| `logs/run_inputs/pipelines/contract.json` | PREPARE | Channels, objects, versions, input file sizes/times, and pipeline checksums |
| `logs/<plate>/illumination.*` | ILLUMINATION | Log, metrics JSON, and LoadData CSV |
| `logs/<plate>/batch_*.log` | ANALYSIS | CellProfiler task logs |
| `logs/<plate>/batch_*.metrics.json` | ANALYSIS | Task timing and resource measurements |
| `logs/<plate>/batch_*.load_data.csv` | ANALYSIS | Exact image and correction file paths used |
| `logs/<plate>/batch_*.validation.json` | ANALYSIS | Validation results and measurement repairs |
| `logs/<plate>/merge.json` | MERGE | Per-plate merge summary |
| `logs/all_plates.merge.json` | CONCAT | Combined table summary |
| `logs/status-*.json` | Workflow completion | Success flag, exit status, duration, session, command, error |
| `logs/nextflow-*.log` | Workflow completion | Saved copy of the launch log when available |

With `--project`, Nextflow writes `report/report.html`, `report/timeline.html`, and `report/trace.txt` in the project folder.
Without `--project`, it writes them in the launch folder, because the session ID is not known when the profile loads.
The HTML report summarizes task resources. The timeline shows when tasks ran.
The launch folder keeps `.nextflow.log`.
Early startup failures may not produce project outputs. Use `.nextflow.log` in that case.

Batch tables, mask manifests, and per-plate tables remain in the work directory.
Only the combined feature table is published. Both profiles preserve work files.

## Check the run before using the data

1. Confirm that Nextflow finished successfully.
2. Read the newest status file and check `success` is true.
3. Check that the combined CSV exists and the merge summaries cover your plates.
4. Review batch validation reports and inspect representative masks over the raw images.

Partial outputs can exist after a failure. Passing file checks does not prove biological accuracy.

## Interpret the per-cell table

| Columns | Meaning |
|---|---|
| `Metadata_Plate`, `Metadata_Well`, `Metadata_Site`, `Metadata_X`, `Metadata_Y` | Image identity |
| `Metadata_Acquisition` | Shared filename prefix, such as `A02_s1_x0_y0` |
| `Metadata_Batch`, `Metadata_ImageNumber` | Batch identity and batch-local image number |
| `Metadata_PlateImageNumber` | Image position in the sorted plate manifest |
| `Metadata_ObjectNumber` | Cell label in the Cells mask |
| `Cells_*`, `Cytoplasm_*`, `Nuclei_*` | Measurements from those cell compartments |
| `Image_*` | Whole-image measurements repeated for each cell row |

Rows follow plate name order, then plate image order, then cell number.
Measurements are copied as text without rounding.
An image with no cells contributes no cell rows. Use manifests and reports to check image coverage.
Nuclei join through their parent-cell relationships, not by assuming matching label numbers.
Empty cytoplasm can produce `nan` measurements or blank fields when CellProfiler omits a row.
Do not replace these values with zero without deciding what that means for your analysis.

For large tables, use pandas `read_csv` with `usecols` or `chunksize` to limit memory.
The gzip output contains multiple gzip members. Python's gzip reader supports this format.
See the [tested reading pattern](tutorials/first-run.md#4-read-a-few-cell-identifiers).

## Match a row to a mask

Use this relative path:

```text
masks/<Metadata_Plate>/<Metadata_Acquisition>_Cells.tiff
```

Pixel value zero means background. Pixels equal to `Metadata_ObjectNumber` belong to that cell.
Object numbers are local to an image and object type. They are not global cell identifiers.
The TIFF description contains JSON metadata, source files, and pipeline steps.
The default pipeline saves Cells, CellsPaired, Cytoplasm, Nuclei, and NucleiPaired masks.

## Checks performed by the software

Analysis checks the exact image sets, module errors, mask types, mask provenance, counts, labels, and measured areas.
It checks that each object's measured area equals its mask pixel count.
Merge rejects missing or unvalidated batches, mismatched columns, inconsistent parent links, and repeated image sets.
Concatenation rejects differences in column names or order between plate tables.
See [troubleshooting](how-to/troubleshooting.md) if any check fails.
