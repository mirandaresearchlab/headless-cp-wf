# Input file formats

Use this reference to check image names and channel assignments.

The filename expression below comes directly from the illumination pipeline.
`bin/make_samplesheet.py` uses it to read the metadata from file names. The workflow itself does not.
PREPARE requires the same channel rules in both pipelines.

```text
^(?P<Well>(?P<Row>[A-P])(?P<Column>[0-9]{2}))_s(?P<Site>[0-9]+)_x(?P<X>[0-9]+)_y(?P<Y>[0-9]+)_Fluorescence_(?P<Wavelength>[0-9]+)_nm_Ex\.tiff?$
```

| Filename channel | CellProfiler image name |
|---|---|
| 405 | DNA |
| 488 | RNA |
| 561 | AGP |
| 638 | Mito |
| 730 | ER |

Images must be unsigned 8-bit or 16-bit grayscale TIFFs with one series and one page.
The image axes must be YX. Every image within a plate must have the same dimensions.
For `bin/make_samplesheet.py`, the plate name is the parent folder, after resolving file links.

## Samplesheet

The samplesheet (`--input`) gives the metadata and the path of each image file.
The files can have any names and be in any folder.
The samplesheet is a CSV file with one row per image file:

```text
plate,well,site,channel,path
plate1,A02,1,DNA,/data/plate1/A02_s1_w1.tiff
plate1,A02,1,RNA,/data/plate1/A02_s1_w2.tiff
```

| Column | Required | Meaning |
|---|---|---|
| `plate` | Yes | Plate name. It must start with a letter or digit. Other characters may be letters, digits, dots, underscores, or hyphens. |
| `well` | Yes | Well, for example `A02`. |
| `site` | Yes | Site (field of view) in the well, for example `1`. |
| `channel` | Yes | CellProfiler image name from the pipelines, for example `DNA`. See the table above. |
| `path` | Yes | The TIFF file. A relative path starts from the folder of the samplesheet. |
| `acquisition` | No | Name of the image set in mask file names and `Metadata_Acquisition`. Default: `<well>_s<site>`. |
| any other | No | More metadata. A column `x` becomes `Metadata_X` in the per-cell table. |

The rows with the same plate, well, site, and other metadata form one image set.
Each image set needs exactly one file for each channel of the pipelines.
Do not use the columns `batch`, `plateImageNumber`, `imageNumber`, and `objectNumber`. The workflow writes them itself.
PREPARE checks every row and every file before the first CellProfiler task starts.

Each run writes its samplesheet to `logs/run_inputs/samplesheet.csv`.
To make a samplesheet from a folder of images, use `bin/make_samplesheet.py` (see [helper scripts](cli.md)).
Check the result, delete rows that you do not want, then give it with `--input`.

## Manifests

Generated manifests use one CSV row per image set, with metadata and a path/filename pair for each channel.
The workflow creates these manifests from the samplesheet or the image folder.

Metadata includes Plate, Well, Site, the other filename or samplesheet fields (for these images: Row, Column, X, Y), Acquisition, and Batch.
See [input layout](../usage.md) and [output formats](../output.md).
