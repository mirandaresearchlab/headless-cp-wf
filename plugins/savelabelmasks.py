"""CellProfiler module that saves one label mask per object type, without losing any label.

A label mask is an image where every pixel holds the number of the object it belongs to
(0 = background). The masks are saved as uint32 TIFFs, so even very large object numbers fit.
The module does not segment anything and does not renumber anything.

Each mask's TIFF description holds JSON that says where the mask came from. It names the
image set and the object type. It lists the pipeline steps that made the mask, and the raw
images and illumination functions those steps read.
"""

import csv
import json
from pathlib import Path

import numpy as np
import tifffile
from cellprofiler_core.module import Module
from cellprofiler_core.preferences import get_default_output_directory
from cellprofiler_core.setting import SettingsGroup
from cellprofiler_core.setting.subscriber import (
    ImageListSubscriber,
    ImageSubscriber,
    LabelListSubscriber,
    LabelSubscriber,
)
from cellprofiler_core.setting.text import ImageName, LabelName

# Settings that name a new image or object (what a module makes).
OUTPUTS = (ImageName, LabelName)

# Settings that pick an existing image or object (what a module reads).
INPUTS = (ImageSubscriber, LabelSubscriber, ImageListSubscriber, LabelListSubscriber)


def names(settings, kinds):
    """Collect the image or object names from the settings of the given kinds.

    Args:
        settings: CellProfiler settings of one module.
        kinds: the setting classes to look at, e.g. OUTPUTS or INPUTS.

    Returns:
        A list of names. Empty values and "None" are skipped.
    """
    found = []
    for setting in settings:
        if isinstance(setting, kinds):

            # Some settings hold one name, others a list of names.
            values = (
                setting.value if isinstance(setting.value, list) else [setting.value]
            )
            found += [v for v in values if v and v != "None"]
    return found


def producers(modules):
    """Find, for each image and object, the module that made it and what that module read.

    Some modules make several outputs in groups, e.g. CorrectIlluminationApply makes CorrDNA
    from DNA and IllumDNA, and CorrRNA from RNA and IllumRNA. An output in a group depends only
    on the inputs of its own group, so CorrDNA does not get RNA as an input.

    Args:
        modules: the pipeline modules that run before this one.

    Returns:
        A dict: name -> (module, list of input names).
    """
    result = {}
    for module in modules:

        # The repeated groups of a module, e.g. one group per channel.
        groups = [
            g
            for value in vars(module).values()
            if isinstance(value, list)
            for g in value
            if isinstance(g, SettingsGroup)
        ]
        grouped = {id(s) for g in groups for s in g.visible_settings()}
        shared = [s for s in module.visible_settings() if id(s) not in grouped]
        every = names(module.visible_settings(), INPUTS)

        # An output outside the groups may depend on every input of the module.
        for name in names(shared, OUTPUTS):
            result[name] = (module, every)

        # An output inside a group depends on its own group and the shared settings only.
        for group in groups:
            for name in names(group.visible_settings(), OUTPUTS):
                result[name] = (
                    module,
                    names(group.visible_settings(), INPUTS) + names(shared, INPUTS),
                )
    return result


def lineage(name, made_by, measurements, steps, sources):
    """Walk back from an object to the files that CellProfiler loaded for it.

    The function follows the inputs of each module, step by step, until it reaches an image
    that LoadData loaded. Loaded images have a FileName_<name> measurement.

    Args:
        name: the image or object to trace, e.g. "Nuclei".
        made_by: the result of producers().
        measurements: the CellProfiler measurements of the current image set.
        steps: a list that collects the modules on the way. Filled in place.
        sources: a dict that collects the loaded files. Filled in place.

    Raises:
        ValueError: if no module made the name and it was not loaded either.
    """

    # Each name is traced only once, even if several steps use it.
    if name in sources or any(s["output"] == name for s in steps):
        return

    # A loaded file: record its name and folder, and stop here.
    if measurements.has_feature("Image", "FileName_" + name):
        sources[name] = dict(
            file=str(measurements.get_current_image_measurement("FileName_" + name)),
            folder=str(measurements.get_current_image_measurement("PathName_" + name)),
        )
        return
    if name not in made_by:
        raise ValueError(f"Cannot trace the origin of {name}")

    # A module made this name: record the step, then trace each of its inputs.
    module, inputs = made_by[name]
    steps.append(
        dict(
            output=name,
            module=module.module_name,
            module_num=module.module_num,
            inputs=inputs,
        )
    )
    for item in inputs:
        lineage(item, made_by, measurements, steps, sources)


class SaveLabelMasks(Module):
    """Pipeline module that prepare.adapt() adds after segmentation. It has no settings.

    For each image set it writes masks/<acquisition>_<Object>.tiff and adds a row
    to mask_manifest.csv. run_task.py reads that manifest to check the masks.
    """

    module_name = "SaveLabelMasks"
    category = "File Processing"
    variable_revision_number = 1

    def create_settings(self):
        """CellProfiler calls this to make the settings. This module has none."""
        pass

    def settings(self):
        """CellProfiler calls this to save the module. No settings, so the list is empty."""
        return []

    def run(self, workspace):
        """Save one mask per object type for the current image set.

        Args:
            workspace: the CellProfiler workspace. It holds the objects, the measurements
                and the pipeline.

        Raises:
            ValueError: if a mask is not 2D, has labels that do not fit in uint32, or would
                overwrite another mask.
        """
        output = Path(get_default_output_directory())
        masks = output / "masks"
        masks.mkdir(exist_ok=True)
        m = workspace.measurements

        # The keys that name this image set, and all its metadata for the provenance JSON.
        metadata = {
            key: str(m.get_current_image_measurement("Metadata_" + key))
            for key in ("Plate", "Batch", "Acquisition")
        }
        acquisition = {
            f[len("Metadata_") :]: str(m.get_current_image_measurement(f))
            for f in m.get_feature_names("Image")
            if f.startswith("Metadata_")
        }

        # Only modules that run before this one can have made the objects.
        made_by = producers(
            module
            for module in workspace.pipeline.modules()
            if module.module_num < self.module_num
        )

        # mask_manifest.csv gets one row per mask. Write the header only the first time.
        manifest = output / "mask_manifest.csv"
        exists = manifest.exists()
        with manifest.open("a", newline="") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=[
                    "Plate",
                    "Batch",
                    "Acquisition",
                    "ImageNumber",
                    "ObjectType",
                    "MaskPath",
                    "LabelCount",
                ],
            )
            if not exists:
                writer.writeheader()
            for name in sorted(workspace.object_set.object_names):
                objects = workspace.object_set.get_objects(name)
                labels = objects.segmented
                if (
                    labels.ndim != 2
                    or labels.min() < 0
                    or labels.max() > np.iinfo(np.uint32).max
                ):
                    raise ValueError(
                        f"{name}: unsupported mask dimensionality or labels"
                    )

                # Same name as the raw images, e.g. A02_s1_x0_y0_Cells.tiff. The plate is the folder.
                filename = f"{metadata['Acquisition']}_{name}.tiff"
                destination = masks / filename
                if destination.exists():
                    raise ValueError(f"Mask filename collision: {destination}")

                # Trace which pipeline steps and which files made this object.
                steps, sources = [], {}
                lineage(name, made_by, m, steps, sources)
                provenance = dict(
                    object=name,
                    image_number=int(m.image_set_number),
                    metadata=acquisition,
                    labels=f"Pixel value = ObjectNumber of {name}; 0 = background",
                    source_files=sources,
                    steps=steps,
                )

                # zlib compression is lossless. The provenance goes into the TIFF description.
                tifffile.imwrite(
                    destination,
                    labels.astype(np.uint32),
                    photometric="minisblack",
                    compression="zlib",
                    description=json.dumps(provenance),
                    metadata=None,
                )
                writer.writerow(
                    dict(
                        metadata,
                        ImageNumber=m.image_set_number,
                        ObjectType=name,
                        MaskPath="masks/" + filename,
                        LabelCount=int(np.count_nonzero(np.unique(labels))),
                    )
                )
