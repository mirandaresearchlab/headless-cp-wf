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

## Cellpose-SAM

The workflow supports the [RunCellpose](https://plugins.cellprofiler.org/runcellpose.html#cellpose-sam-cellpose-4)
module with Cellpose-SAM (Cellpose 4, model `cpsam`). Put RunCellpose modules in `2_analysis.cppipe`.
`cp-configs-cellpose/` is an example: Cellpose-SAM finds the nuclei, and the other modules are the same as in `cp-configs/`.

### Why segmentation is a separate step

Cellpose-SAM is a large neural network. It is much faster on a GPU than on a CPU.
The measurement modules after it use only CPUs, and they take most of the time of an analysis task.
If one task did both, the GPU would wait while the CPU measures.

So the workflow cuts the analysis pipeline in two parts:

| Part | Runs | Contains |
|---|---|---|
| SEGMENT | `--segmentation gpu` or `cpu` | The RunCellpose modules, and only the modules that make their input images (for example CorrectIlluminationApply). At the end, SaveLabelMasks saves one mask per image set and object. |
| ANALYSIS | Always on CPUs | All modules of the pipeline. A LoadLabelMasks module takes the place of each RunCellpose module, with the same input image and the same object name. |

LoadLabelMasks reads the mask that SEGMENT saved, and adds the same objects and measurements as RunCellpose
(Count, Location_Center_X/Y/Z and Number_Object_Number). So all later modules get the same objects as from RunCellpose in the same task.

One SEGMENT task segments `--segmentation_batches` consecutive batches of one plate.
It starts `--segmentation_workers` CellProfiler processes at the same time, each on a part of the image sets.
On a GPU, the workers share the GPU. One worker loads images or finds the objects on the CPU. At the same time, the others use the GPU.
Each worker may use an equal part of 90% of the GPU memory.
The task writes the GPU use of each second to `logs/<plate>/<group>.gpu.csv`, and the mean to `<group>.metrics.json`.

### How the masks stay linked to their images

A mask goes from SEGMENT to ANALYSIS only after these checks pass:

1. SEGMENT: every image set of the group has exactly one mask per Cellpose object. No mask is missing or saved twice.
2. SEGMENT: the TIFF description of each mask names its plate, batch and image set.
   It also names exactly the raw images and illumination files of this image set. The label count matches.
3. Nextflow gives each ANALYSIS task the SEGMENT folder of its own plate and batch, by name.
   The run stops if a batch has no folder or two folders.
4. ANALYSIS: the folder is for this plate and batch, and holds the masks of exactly its image sets.
5. LoadLabelMasks: before it uses a mask, it checks again that the mask names the current image set and files.
6. ANALYSIS: the mask that it saves at the end for each Cellpose object must equal the SEGMENT mask, label for label.

So a mask cannot be used for another image set, and its object numbers do not change.
The object number in the per-cell table is the label in the published mask.
The masks of the Cellpose objects are in `masks/<plate>/` with the other masks.

### Settings that the workflow changes or rejects

The source pipeline does not change. In the working copies, PREPARE and SEGMENT change only where Cellpose runs:

- "Run CellPose in a Docker/Podman container or local python environment" becomes Python. The environment has cellpose 4.0.6, the version of the RunCellpose Docker image for Cellpose 4.
- "Use GPU" follows `--segmentation`. "GPU memory share for each worker" is 0.9 divided by the number of workers.
- "Cache model between image sets" becomes Yes, so each worker loads the model once.

PREPARE stops the run if a RunCellpose module:

- is not Cellpose version v4 (Cellpose-SAM),
- uses 3D,
- saves the probability image (only objects go from SEGMENT to ANALYSIS),
- uses a custom model that is not a file in an absolute folder ("Elsewhere...").

PREPARE also stops the run if the nuclei or the cytoplasm have no `Parent_<cells>` measurement, because MERGE joins them to their cell with it.
If Cellpose finds the cells and the nuclei separately, relate them with RelateObjects.
MERGE stops if a cell has more than one nucleus, because one row per cell would then be ambiguous.

`plugins/runcellpose.py` is a copy of the RunCellpose plugin at a fixed version, with three corrections for Cellpose 4.
Its first lines list them. With the corrections, each worker keeps the model loaded between image sets.
A Cellpose error stops the task. And "Remove objects that are touching the edge? No" keeps the edge objects.

### CPU and GPU results

Cellpose-SAM on a GPU and on a CPU do not give bit-identical masks, because the numerical libraries differ.
Do not mix CPU and GPU segmentation in one screen if you compare plates with each other.
Each run records the device in `logs/<plate>/<group>.metrics.json`.
