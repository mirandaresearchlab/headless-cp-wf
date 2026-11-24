# Run a small example

This tutorial uses small crops of your own images to check the complete workflow.
It uses the example pipelines in `cp-configs`. For other images, [provide your own pipelines](../usage.md#provide-your-own-pipelines).

Prerequisites: complete [installation](../getting-started/installation.md) and activate `cp-headless`.
You need an image folder with one folder per plate. Each plate needs five channels for sites `A02_s1` and `A03_s1`.
Run every command from the repository root.
Use new names for the fixture and project.

!!! note "Validation scope"
    We ran steps 1 to 3 on Berzelius with three real plates and the example pipelines.
    The run completed with 14 tasks in about 5 minutes on 2 cores.
    A full-size dataset can take hours.

## 1. Create small images

```bash
python tests/make_fixture.py <images> example-images
```

For three plates, the expected message is:

```text
Created 30 crops in example-images
```

The script takes the top-left 1024 × 1024 pixels from five channels at two sites per plate.
Smaller crops do not work with the example pipelines: CellProfiler stops when an image is
less than twice the adaptive threshold window (501 pixels). PREPARE checks this before any
CellProfiler task, and stops the run with the module, the window and the image size.
The script also writes `example-images.json` with source checksums and crop details.
It stops if the destination already exists. Cropped images are for testing, not scientific conclusions.

## 2. Make the samplesheet

```bash
python bin/make_samplesheet.py --images example-images --configs cp-configs --out example-samplesheet.csv
```

For three plates, the expected message is:

```text
Wrote example-samplesheet.csv: 6 image sets, 30 files
```

## 3. Run all five workflow steps

```bash
nextflow run . -profile local \
  --input example-samplesheet.csv \
  --configs cp-configs \
  --project tutorial \
  --batch_size 1
```

Nextflow prints the actual output folder and a resume command.
For three plates with two image sets each, preparation plans six analysis batches.
The run has 13 tasks: one preparation, three illumination, six analysis, and three merges.

## 4. Check completion

Open the output folder printed by Nextflow. A fresh project normally uses `projects/tutorial/`.
Check that the newest `logs/status-*.json` contains `"success": true`.
Do not treat the presence of masks alone as proof of completion.

Expected layout:

```text
projects/tutorial/
  run.json
  illum/
  masks/
  cp_features/<plate>.parquet   (one file per plate)
  logs/
```

The supplied pipeline produces five masks per image set, or 30 masks for this example.
The number of cell rows depends on the crop. It is not a fixed acceptance target.
Read [output checks](../output.md) before interpreting the data.

## 5. Read a few cell identifiers

This command uses pandas and pyarrow from `cp-headless`. It reads all plate files of the folder as one table,
and only the three columns it needs. Adjust the path if Nextflow chose another project folder.

```bash
python - <<'PYTHON'
import pandas as pd
cells = pd.read_parquet('projects/tutorial/cp_features', columns=['Metadata_Plate', 'Metadata_Acquisition', 'Metadata_ObjectNumber'])
print(cells.head())
PYTHON
```

Expected output: a table of up to five rows, each with a plate name, acquisition name, and cell number.
This read command was checked with plate tables converted from a saved tutorial run, not a new full workflow run.
Continue with [your own images](../usage.md) or [troubleshooting](../how-to/troubleshooting.md).
