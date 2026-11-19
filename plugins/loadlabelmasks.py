"""CellProfiler module that loads the label masks of a SEGMENT task in place of RunCellpose.

The workflow runs the RunCellpose modules in their own SEGMENT task, on a GPU or a CPU. The
analysis copy of the pipeline then has one LoadLabelMasks module at the position of each
RunCellpose module, with the same input images and the same object name. So every later module
gets the same objects as if RunCellpose had run in the same task.

The module reads <Default Input Folder>/<folder>/<acquisition>_<object>.tiff, which SaveLabelMasks
wrote in the SEGMENT task. Before it uses a mask, it checks that the mask names this image set
(Plate, Batch, Acquisition) and exactly the raw images and illumination functions that this image
set loaded. It records the same measurements as RunCellpose: Count, Location_Center_X/Y/Z and
Number_Object_Number.
"""

import json
from pathlib import Path

import tifffile
from cellprofiler_core.module.image_segmentation import ImageSegmentation
from cellprofiler_core.object import Objects
from cellprofiler_core.preferences import get_default_image_directory
from cellprofiler_core.setting.subscriber import ImageSubscriber
from cellprofiler_core.setting.text import Text


def check_provenance(provenance, name, measurements):
    """Check that a mask belongs to the current image set and was made from its files.

    Parameters
    ----------
    provenance : dict
        The JSON in the TIFF description, as SaveLabelMasks wrote it.
    name : str
        The object name that this module makes.
    measurements : cellprofiler_core.measurement.Measurements
        The measurements of the current image set.

    Raises
    ------
    ValueError
        If the mask is for another object, another image set, or other files.
    """
    current = {
        key: str(measurements.get_current_image_measurement("Metadata_" + key))
        for key in ("Plate", "Batch", "Acquisition")
    }
    named = {key: provenance["metadata"].get(key) for key in current}
    if provenance["object"] != name or named != current:
        raise ValueError(f"Mask is for {provenance['object']} {named}, not {name} {current}")

    # The files that made the mask must be the files that this image set loaded.
    files = provenance["source_files"]
    if not files:
        raise ValueError(f"Mask of {name} {current} names no source files")
    for image, source in sorted(files.items()):
        loaded = dict(
            file=str(measurements.get_current_image_measurement("FileName_" + image)),
            folder=str(measurements.get_current_image_measurement("PathName_" + image)),
        )
        if loaded != source:
            raise ValueError(f"Mask of {name} {current} was made from {image} {source}, but this image set loaded {loaded}")


class LoadLabelMasks(ImageSegmentation):
    """Pipeline module that ``prepare.split_segmentation()`` puts in place of RunCellpose."""

    module_name = "LoadLabelMasks"
    category = "Object Processing"
    variable_revision_number = 1

    def create_settings(self):
        """Make the settings: the input images and the object name of RunCellpose, and the folder."""
        super().create_settings()
        self.nuclei_image = ImageSubscriber(
            "Select the nuclei image", can_be_blank=True, blank_text="None"
        )
        self.folder = Text("Mask folder in the Default Input Folder", "segmentation/masks")

    def settings(self):
        """Return the settings in the order that the .cppipe file stores them."""
        return [self.x_name, self.nuclei_image, self.y_name, self.folder]

    def visible_settings(self):
        """Return all settings. SaveLabelMasks reads the input images from them."""
        return self.settings()

    def run(self, workspace):
        """Load the mask of the current image set, check it, and add the objects.

        Parameters
        ----------
        workspace : cellprofiler_core.workspace.Workspace
            Holds the image set, the objects and the measurements.

        Raises
        ------
        ValueError
            If the mask is not a 2D label image of the input image size, or its provenance
            does not match the current image set.
        """
        name = self.y_name.value
        measurements = workspace.measurements
        acquisition = measurements.get_current_image_measurement("Metadata_Acquisition")
        path = Path(get_default_image_directory()) / self.folder.value / f"{acquisition}_{name}.tiff"
        with tifffile.TiffFile(path) as tiff:
            labels = tiff.asarray()
            provenance = json.loads(tiff.pages[0].description)
        check_provenance(provenance, name, measurements)

        image = workspace.image_set.get_image(self.x_name.value)
        if labels.ndim != 2 or labels.shape != image.pixel_data.shape[:2]:
            raise ValueError(f"Mask {path.name} has shape {labels.shape}, image {self.x_name.value} has {image.pixel_data.shape}")

        objects = Objects()
        objects.segmented = labels
        objects.parent_image = image.parent_image
        workspace.object_set.add_objects(objects, name)
        self.add_measurements(workspace)
