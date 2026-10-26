# Run a small example

This tutorial uses small crops of your own images to check the complete workflow.

Prerequisites: complete [installation](../getting-started/installation.md) and activate `cp-headless`.
You need an image folder with one folder per plate. Each plate needs five channels for sites `A02_s1` and `A03_s1`.
Run every command from the repository root.
Use new names for the fixture and project.

!!! note "Validation scope"
    Fixture creation was tested during this documentation update.
    The Nextflow run below was reviewed against the code but not executed here.
    Nextflow and CellProfiler were unavailable. Runtime for the cropped example is not yet measured.
    Allow extra time for a first run. A full-size dataset can take hours.

## 1. Create small images

```bash
python tests/make_fixture.py <images> example-images
```

For three plates, the expected message is:

```text
Created 30 crops in example-images
```

The script takes the top-left 512 × 512 pixels from five channels at two sites per plate.
It also writes `example-images.json` with source checksums and crop details.
It stops if the destination already exists. Cropped images are for testing, not scientific conclusions.

## 2. Run all five workflow steps

```bash
nextflow run . -profile local \
  --images example-images \
  --configs cp-configs \
  --project tutorial \
  --batch_size 1
```

Nextflow prints the actual output folder and a resume command.
For three plates with two image sets each, preparation plans six analysis batches.
The run has 14 tasks: one preparation, three illumination, six analysis, three merges, and one concatenation.

## 3. Check completion

Open the output folder printed by Nextflow. A fresh project normally uses `projects/tutorial/`.
Check that the newest `logs/status-*.json` contains `"success": true`.
Do not treat the presence of masks alone as proof of completion.

Expected layout:

```text
projects/tutorial/
  run.json
  illum/
  masks/
  cp_features/all_plates.csv.gz
  logs/
```

The supplied pipeline produces five masks per image set, or 30 masks for this example.
The number of cell rows depends on the crop. It is not a fixed acceptance target.
Read [output checks](../output.md) before interpreting the data.

## 4. Read a few cell identifiers

This command uses Python's standard library. Adjust the path if Nextflow chose another project folder.

```bash
python - <<'PYTHON'
import csv
import gzip
from itertools import islice
with gzip.open('projects/tutorial/cp_features/all_plates.csv.gz', 'rt') as stream:
    for row in islice(csv.DictReader(stream), 5):
        print(row['Metadata_Plate'], row['Metadata_Acquisition'], row['Metadata_ObjectNumber'])
PYTHON
```

Expected output: up to five lines, each with a plate name, acquisition name, and cell number.
This read command was checked with a saved plate table, not a new full workflow run.
Continue with [your own images](../usage.md) or [troubleshooting](../how-to/troubleshooting.md).
