# Understand segmentation

Segmentation assigns image pixels to objects such as nuclei and cells.

The supplied analysis pipeline applies illumination correction before identifying objects.
It identifies primary nuclei, then grows secondary cell objects using watershed segmentation.
Watershed divides image regions around seed objects using the configured image or gradient.
The tertiary-object step derives cytoplasm from the cell and nucleus objects.

The pipeline measures size, shape, intensity, texture, and other configured features.
See the [generated module list](../reference/pipelines.md) for the exact execution order.
PREPARE preserves segmentation and measurement settings in its working copies.
It adds mask export and changes data-loading and table-export settings.

The final table joins Cells, Nuclei, and Cytoplasm measurements.
Additional paired cell and nucleus object types also receive masks for inspection.
The automatic checks compare measured areas with mask pixels and check object relationships.

Check overlays of masks on representative raw images before interpreting measurements.
A mask can pass every file check and still split or merge biological cells incorrectly.
The repository does not document the biological rationale for every threshold and filter.
Consult the pipeline author before changing those settings for a new experiment.
