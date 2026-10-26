# Input file formats

Use this reference to check image names and channel assignments.

The filename expression below comes directly from the illumination pipeline.
PREPARE requires compatible metadata and channel rules in the analysis pipeline.

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
Plate identity comes from the parent folder after resolving file links.

Generated manifests use one CSV row per image set, with metadata and a path/filename pair for each channel.
The workflow creates these manifests. Users do not supply a separate spreadsheet.

Metadata includes Plate, Well, Row, Column, Site, X, Y, Acquisition, and Batch.
See [input layout](../usage.md) and [output formats](../output.md).
