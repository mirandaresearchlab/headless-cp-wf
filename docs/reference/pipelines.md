# CellProfiler pipelines

This list is generated from the supplied `.cppipe` files in source order.
Both pipelines require CellProfiler and cellprofiler-core 4.2.8.1.

PREPARE replaces the four input modules with LoadData in working copies.
It adds SaveLabelMasks before spreadsheet export and redirects outputs into each task.
It preserves segmentation and measurement settings. The source files stay unchanged.

LoadData manifests contain `Metadata_*`, `FileName_<channel>`, and `PathName_<channel>` fields.
Analysis adds `FileName_Illum<channel>` and `PathName_Illum<channel>` fields.
See [file formats](file-formats.md) and [outputs](../output.md).

## 1_illumination.cppipe

| Module number | Module |
|---|---|
| 1 | Images |
| 2 | Metadata |
| 3 | NamesAndTypes |
| 4 | Groups |
| 5 | CorrectIlluminationCalculate |
| 6 | CorrectIlluminationCalculate |
| 7 | CorrectIlluminationCalculate |
| 8 | CorrectIlluminationCalculate |
| 9 | CorrectIlluminationCalculate |
| 10 | SaveImages |
| 11 | SaveImages |
| 12 | SaveImages |
| 13 | SaveImages |
| 14 | SaveImages |

## 2_analysis.cppipe

| Module number | Module |
|---|---|
| 1 | Images |
| 2 | Metadata |
| 3 | NamesAndTypes |
| 4 | Groups |
| 5 | CorrectIlluminationApply |
| 6 | MeasureImageQuality |
| 7 | ImageMath |
| 8 | IdentifyPrimaryObjects |
| 9 | IdentifySecondaryObjects |
| 10 | FilterObjects |
| 11 | MaskObjects |
| 12 | RelateObjects |
| 13 | IdentifyTertiaryObjects |
| 14 | MeasureObjectSizeShape |
| 15 | MeasureObjectIntensity |
| 16 | MeasureImageIntensity |
| 17 | MeasureColocalization |
| 18 | MeasureGranularity |
| 19 | MeasureTexture |
| 20 | MeasureObjectIntensityDistribution |
| 21 | MeasureObjectNeighbors |
| 22 | MeasureObjectNeighbors |
| 23 | OverlayOutlines |
| 24 | SaveImages |
| 25 | ExportToSpreadsheet |

