# Change a CellProfiler pipeline

Use this procedure when your image naming or analysis settings differ from the supplied pipelines.

This procedure requires CellProfiler 4.2.8.1 and a representative test dataset.
It was reviewed against PREPARE checks but not executed with a new pipeline during this documentation update.

1. Copy the two pipeline files to a separate configuration folder.
2. Keep their required names: `1_illumination.cppipe` and `2_analysis.cppipe`.
3. Edit and export the copies with the matching CellProfiler version.
4. Keep channel and filename metadata rules consistent in both files.
5. Run a small new project using that folder as `--configs`.
6. Inspect the adapted pipelines, validation reports, and masks.
7. Compare batching behavior before processing a full experiment.

Do not enable grouping, tracking, or modules that need information from other batches.
Illumination must accumulate across cycles and save NPY functions on the last cycle.
Analysis must apply those same functions before traditional nuclei and watershed cell segmentation.
It must define one tertiary-object module for the cell compartments and one spreadsheet exporter.
Absolute output destinations are rejected to prevent jobs writing to the same files.

Do not bypass PREPARE checks to make an incompatible pipeline run.
Some changes require changes to the Python validation and merge code.
See [developer checks](../about/contributing.md) and [design limits](../explanation/design.md).
