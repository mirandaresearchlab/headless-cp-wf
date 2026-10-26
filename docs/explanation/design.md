# Design and limits

This page explains the boundaries of the workflow's checks.

The two pipeline files define image naming, channels, segmentation, and measurements.
PREPARE reads those rules instead of requiring a separate sample spreadsheet.
It creates task-specific copies with LoadData input and safe output locations.
The source pipeline files stay unchanged.

Illumination uses a whole plate because correction functions accumulate across image sets.
Analysis can split into batches only when modules do not depend on other batches.
PREPARE rejects grouping, tracking, aggregation, and other unsupported settings that could violate that condition.
Cellpose is not supported by this workflow.

The per-cell merge expects one set of cell, nucleus, and cytoplasm compartments.
It rejects several nuclei assigned to one cell because that would make one row per cell ambiguous.
The workflow keeps missing measurements when a compartment has no pixels.

File checks detect structural problems. They do not establish that segmentation suits your experiment.
Inspect representative images and masks before a full screen.
Do not apply the supplied biological settings to a new assay without review.
The repository does not provide a complete scientific rationale for those settings.

Reproduce a run by preserving the code revision, input files, pipeline files, environment,
run command, adapted pipeline copies, contract, and validation reports.
The contract records input sizes and modification times, not a cryptographic checksum for every raw image.
Illumination outputs and pipeline files have recorded SHA-256 checksums.
