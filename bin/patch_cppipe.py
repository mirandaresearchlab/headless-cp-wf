#!/usr/bin/env python3
"""Prepare a CellProfiler pipeline for headless runs in chunks.

"Headless" means without the window of CellProfiler. This script uses the Python API of CellProfiler
to read and change the pipeline. It makes these changes, and writes each one into a JSON report:
  * It stops at once if CellProfiler cannot load the pipeline. Two usual causes are a missing plugin
    and a pipeline from a newer CellProfiler.
  * It removes CreateBatchFiles. In a headless run, this module writes a batch file and stops the run.
  * It moves each output folder that points outside the job, or into the image folder, into the job
    folder. Thus each chunk writes into its own folder, and nothing goes into your image folder.
  * For each object type without a mask, it adds ConvertObjectsToImage (16-bit labels) and SaveImages.
    Thus you always get segmentation masks.
  * It adds ExportToSpreadsheet if the pipeline has none. Thus you always get feature tables.
  * It makes ExportToSpreadsheet write Image.csv, Cells.csv, ... into the job folder, without a file name
    prefix and with the image metadata (plate, well, site) in each object table.
  * It sets RunCellpose (plugin) to run Cellpose in the Python of the container (not in Docker), without
    a GPU.
  * With --illum-files, it makes the Images module pass the .npy illumination functions that the workflow
    adds to the file list of each chunk ("Images only" drops them).

With --illum, the script prepares an illumination pipeline instead: no masks and no feature tables. It stops
if the pipeline has no CorrectIlluminationCalculate, or no SaveImages that saves .npy files at the last cycle.

The script runs once per pipeline and workflow run (process PATCH_PIPELINE in main.nf), in the CellProfiler
container. All ILLUM and chunk jobs then use the changed pipelines.

Notes
-----
Exit codes: 0 = success. 1 = CellProfiler cannot load the pipeline, the illumination pipeline is not usable,
or the script cannot change the pipeline (and you did not set --allow-unpatched).
"""

import argparse
import json
import shutil
import sys
import traceback

# CellProfiler modules that write files. The patch moves their output folder into the job folder.
OUTPUT_MODULES = {
    "SaveImages",
    "ExportToSpreadsheet",
    "ExportToDatabase",
    "SaveCroppedObjects",
}

# Modules that load the input images. The first image that they name is the "reference image": the
# patch names each mask file after it.
INPUT_PROVIDERS = {"NamesAndTypes", "LoadData", "LoadImages"}

# Folder choices of CellProfiler. The output folder is the folder of the job (cellprofiler -o).
DEFAULT_OUTPUT = "Default Output Folder"
DEFAULT_OUTPUT_SUB = "Default Output Folder sub-folder"

# Folder choices that can write outside the job folder, or into the image folder.
UNSAFE_DIR_CHOICES = {
    "Elsewhere...",
    "Default Input Folder",
    "Default Input Folder sub-folder",
}
MASK_SUBDIR = "masks"
PREFIX = "CPNF"  # start of the names that this script adds. A second run finds and reuses them.


class LoadFailure(RuntimeError):
    """CellProfiler cannot load the pipeline (for example a missing plugin or a newer pipeline version)."""


class PatchFailure(RuntimeError):
    """The pipeline loads, but the script cannot make a change (for example an unknown object name)."""


def parse_args():
    """Read the command-line options.

    main.nf makes the options from the workflow parameters.

    Returns
    -------
    argparse.Namespace
        The options: input, output, report, mask_format, objects, no_masks, plugins_dir,
        chunked, allow_unpatched, illum and illum_files.
    """
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", required=True, help=".cppipe or .cpproj file")
    p.add_argument("--output", required=True, help="patched .cppipe to write")
    p.add_argument("--report", required=True, help="JSON report to write")
    p.add_argument("--mask-format", default="tiff", choices=["tiff", "png", "npy"])
    p.add_argument("--objects", default=None, help="comma-separated object names to save (default: all)")
    p.add_argument("--no-masks", action="store_true", help="do not inject mask saving")
    p.add_argument("--plugins-dir", default=None)
    p.add_argument(
        "--chunked",
        action="store_true",
        help="the workflow splits image sets into chunks: fail on modules that need all image sets",
    )
    p.add_argument(
        "--allow-unpatched",
        action="store_true",
        help="if patching fails, fall back to the original pipeline instead of failing",
    )
    p.add_argument(
        "--illum",
        action="store_true",
        help="the pipeline calculates illumination functions: no masks, no feature tables",
    )
    p.add_argument(
        "--illum-files",
        action="store_true",
        help="the file list has .npy illumination functions: let them pass the Images filter",
    )
    return p.parse_args()


# --------------------------------------------------------------------------- setup


def init_cellprofiler(plugins_dir):
    """Start CellProfiler without a window, load its modules and plugins, and return its tools.

    The imports are inside the function. Thus a missing CellProfiler gives a clear error in main().

    Parameters
    ----------
    plugins_dir : str or None
        Folder with CellProfiler plugins, or None for no plugins.

    Returns
    -------
    Pipeline : type
        The CellProfiler Pipeline class.
    instantiate_module : callable
        Makes a new module from its name, for example ``instantiate_module("SaveImages")``.
    version : str
        The CellProfiler version, for example "4.2.8", or "unknown".
    """
    from cellprofiler_core.preferences import set_headless

    set_headless()

    # Older CellProfiler versions have no "globally" argument.
    if plugins_dir:
        from cellprofiler_core.preferences import set_plugin_directory

        try:
            set_plugin_directory(plugins_dir, globally=False)
        except TypeError:  # the older function has no 'globally' argument
            set_plugin_directory(plugins_dir)

    from cellprofiler_core.utilities.core.modules import fill_modules, instantiate_module

    fill_modules()
    from cellprofiler_core.pipeline import Pipeline

    try:
        import cellprofiler

        version = getattr(cellprofiler, "__version__", "unknown")
    except ImportError:
        version = "unknown"
    return Pipeline, instantiate_module, version


def version_as_revision(version):
    """Change a CellProfiler version into the DateRevision number of .cppipe files.

    Parameters
    ----------
    version : str
        A version such as "4.2.8".

    Returns
    -------
    int or None
        For example 428 for "4.2.8". None if the version does not have three numbers.
    """
    parts = str(version).split(".")[:3]
    if len(parts) == 3 and all(x.isdigit() for x in parts):
        return int(parts[0]) * 100 + int(parts[1]) * 10 + int(parts[2])
    return None


def pipeline_revision(path):
    """Read the DateRevision number from the header of a .cppipe file.

    Parameters
    ----------
    path : str
        Path of the .cppipe or .cpproj file.

    Returns
    -------
    int or None
        The DateRevision number (428 means CellProfiler 4.2.8). None for a .cpproj file (HDF5),
        or for a header without the line.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for _ in range(10):
                line = fh.readline()
                if line.startswith("DateRevision:"):
                    return int(line.split(":", 1)[1].strip())
    except (OSError, ValueError):
        pass
    return None  # a .cpproj file (HDF5) or a header without the line


def load_pipeline(Pipeline, path):
    """Load the pipeline with CellProfiler, and stop on any problem.

    CellProfiler tells about some problems (for example an unknown module) with events, not with
    exceptions. A listener collects these events. Thus each problem gives a message.

    Parameters
    ----------
    Pipeline : type
        The CellProfiler Pipeline class (from init_cellprofiler).
    path : str
        Path of the .cppipe or .cpproj file.

    Returns
    -------
    cellprofiler_core.pipeline.Pipeline
        The loaded pipeline.

    Raises
    ------
    LoadFailure
        If CellProfiler cannot load the file, or tells about a problem while it loads it.
    """
    pipeline = Pipeline()
    problems = []

    def listener(_caller, event):
        """Collect the load problems that CellProfiler sends as events.

        Parameters
        ----------
        _caller : object
            The object that sends the event (not used).
        event : object
            The event. The listener collects only events of the type LoadException.
        """
        if type(event).__name__ == "LoadException":
            name = getattr(event, "module_name", None) or "unknown module"
            problems.append(f"{name}: {getattr(event, 'error', event)}")

    pipeline.add_listener(listener)
    try:
        pipeline.load(path)
    except Exception as exc:
        raise LoadFailure(f"CellProfiler could not load '{path}': {exc}") from exc
    finally:
        pipeline.remove_listener(listener)
    if problems:
        raise LoadFailure(
            "CellProfiler reported errors while loading the pipeline "
            "(missing plugin or CellProfiler version mismatch?):\n  - " + "\n  - ".join(problems)
        )
    return pipeline


# --------------------------------------------------------------------------- helpers


def is_enabled(module):
    """Tell if a module is on.

    A user can turn a module off in CellProfiler. Such a module does not run.

    Parameters
    ----------
    module : cellprofiler_core.module.Module
        A module of the pipeline.

    Returns
    -------
    bool
        True if the module is on.
    """
    return getattr(module, "enabled", True)


def set_value(setting, value, label):
    """Set a module setting. For a choice setting, first check that it allows the value.

    Parameters
    ----------
    setting : cellprofiler_core.setting.Setting
        The setting to change.
    value : object
        The new value.
    label : str
        Name of the setting for the error message, for example "SaveImages.file_format".

    Raises
    ------
    PatchFailure
        If the setting is a choice and does not allow the value.
    """

    # Only Choice settings carry a fixed list of allowed values.
    if type(setting).__name__ == "Choice" and value not in setting.choices:
        raise PatchFailure(f"{label}: '{value}' is not one of {list(setting.choices)}")
    setting.value = value


def append_module(pipeline, instantiate_module, name):
    """Add a new module with default settings at the end of the pipeline.

    Parameters
    ----------
    pipeline : cellprofiler_core.pipeline.Pipeline
        The pipeline to change.
    instantiate_module : callable
        Makes a module from its name (from init_cellprofiler).
    name : str
        Name of the module, for example "SaveImages".

    Returns
    -------
    cellprofiler_core.module.Module
        The new module.
    """
    module = instantiate_module(name)
    module.set_module_num(len(pipeline.modules()) + 1)
    pipeline.add_module(module)
    return module


def provider_names(pipeline, group):
    """List the image names or the object names that the pipeline makes.

    The function ignores modules that are off.

    Parameters
    ----------
    pipeline : cellprofiler_core.pipeline.Pipeline
        The pipeline.
    group : str
        "imagegroup" for image names (for example DNA), or "objectgroup" for object names
        (for example Nuclei).

    Returns
    -------
    dict
        ``{name: (number of the first module that makes it, set of the names of those modules)}``.
    """
    providers = pipeline.get_provider_dictionary(group)
    out = {}
    for name, provs in providers.items():
        nums = [m.module_num for m, _ in provs if is_enabled(m)]
        if nums:
            out[name] = (min(nums), {m.module_name for m, _ in provs})
    return out


def setting_value(module, attribute):
    """Read a module setting as text.

    Parameters
    ----------
    module : cellprofiler_core.module.Module
        The module.
    attribute : str
        Python name of the setting, for example "each_or_all".

    Returns
    -------
    str
        The value as text, or "" if the module has no such setting.
    """
    setting = getattr(module, attribute, None)
    return str(getattr(setting, "value", ""))


def chunk_unsafe_modules(pipeline):
    """Find the modules that need image sets from more than one chunk.

    Each chunk is a separate CellProfiler run. Thus such a module calculates a result for each chunk,
    without an error. For example, it calculates one illumination correction per chunk, not per plate.

    Parameters
    ----------
    pipeline : cellprofiler_core.pipeline.Pipeline
        The loaded pipeline.

    Returns
    -------
    list of str
        One line per module that is on. Each line gives the module number, the name and the reason.
        Example: "#4 CorrectIlluminationCalculate: calculates one illumination function ...".
    """
    found = []

    # Look at each module that is on, and note the reason if it needs image sets from other chunks.
    for module in pipeline.modules():
        if not is_enabled(module):
            continue
        name = module.module_name
        reason = None
        if name == "LoadData":
            reason = "reads its own CSV, so every chunk would process all image sets in it"
        elif name == "Groups" and module.wants_groups.value:
            reason = "groups image sets, and chunks can split a group"
        elif name == "CorrectIlluminationCalculate":
            mode = setting_value(module, "each_or_all")
            if mode.startswith("All"):
                reason = (
                    f"calculates one illumination function from all images ({mode!r}), "
                    "but each chunk would calculate its own"
                )
        elif name in ("TrackObjects", "MakeProjection", "CalculateStatistics"):
            reason = "combines measurements or images from several image sets"
        elif name == "Tile" and "across" in setting_value(module, "tile_method").lower():
            reason = "tiles images across image sets"
        if reason:
            found.append(f"#{module.module_num} {name}: {reason}")
    return found


# --------------------------------------------------------------------------- patch steps


def remove_batch_modules(pipeline, report):
    """Remove CreateBatchFiles from the pipeline.

    In a headless run, CreateBatchFiles writes a batch file and then stops the run.

    Parameters
    ----------
    pipeline : cellprofiler_core.pipeline.Pipeline
        The pipeline to change.
    report : dict
        The report. The function adds each removed module to ``report["removed_modules"]``.
    """

    # Go from the end to the start, so that removing a module does not change the numbers of the rest.
    for module in reversed(list(pipeline.modules())):
        if module.module_name == "CreateBatchFiles":
            pipeline.remove_module(module.module_num)
            report["removed_modules"].append("CreateBatchFiles")


def redirect_outputs(pipeline, report):
    """Move each output folder that points outside the job, or into the image folder, into the job folder.

    For example, "Elsewhere...|/home/me/out" becomes "Default Output Folder sub-folder|out". Thus each
    chunk writes into its own folder, and nothing goes into the image folder.

    Parameters
    ----------
    pipeline : cellprofiler_core.pipeline.Pipeline
        The pipeline to change.
    report : dict
        The report. Each change goes to ``report["redirected"]``. A warning about numbered file
        names goes to ``report["warnings"]``.
    """
    for module in pipeline.modules():
        if module.module_name not in OUTPUT_MODULES or not is_enabled(module):
            continue

        # SaveImages.root_dir tells where the input images are, so that SaveImages can copy their sub-folders.
        # It must keep pointing at the input side. Thus this loop does not change it.
        input_side = {id(getattr(module, "root_dir", None))}

        # A folder setting has the form "<choice>|<custom path>". Keep only the last folder name of
        # the custom path, below the job's output folder.
        for setting in module.settings():
            if "Directory" not in type(setting).__name__ or id(setting) in input_side:
                continue
            choice, _, custom = str(setting.value).partition("|")
            if choice not in UNSAFE_DIR_CHOICES:
                continue
            sub = custom.replace("\\", "/").rstrip("/").split("/")[-1] if custom else ""
            new = f"{DEFAULT_OUTPUT_SUB}|{sub}" if sub else f"{DEFAULT_OUTPUT}|"
            report["redirected"].append(
                {
                    "module": f"#{module.module_num} {module.module_name}",
                    "from": setting.value,
                    "to": new,
                }
            )
            setting.value = new

        # Numbered file names start again at 1 in each chunk, so two chunks would write the same names.
        if module.module_name == "SaveImages" and module.file_name_method.value == "Sequential numbers":
            report["warnings"].append(
                f"#{module.module_num} SaveImages uses 'Sequential numbers'; numbering restarts in every "
                "chunk, so files from different chunks will share names. Prefer 'From image filename'."
            )


def managed_mask_writers(pipeline):
    """Find the mask writers that an earlier run of this script added.

    The script names its mask modules with the start CPNF_. In a pipeline that the script already
    changed, the function finds these modules. Thus a second run adds no second set of masks.

    Parameters
    ----------
    pipeline : cellprofiler_core.pipeline.Pipeline
        The pipeline.

    Returns
    -------
    list of dict
        One dict per mask writer, with the keys object, label_image, suffix, format and
        reference_image.
    """

    # Which label image belongs to which object: {CPNF_Nuclei_labels: Nuclei, ...}.
    converted = {}
    for m in pipeline.modules():
        if is_enabled(m) and m.module_name == "ConvertObjectsToImage":
            converted[m.image_name.value] = m.object_name.value

    # A SaveImages module counts as ours only if it saves a CPNF_ label image into the masks folder.
    managed = []
    for module in pipeline.modules():
        if not is_enabled(module) or module.module_name != "SaveImages":
            continue
        image_name = module.image_name.value
        if (
            module.save_image_or_figure.value != "Image"
            or not image_name.startswith(f"{PREFIX}_")
            or image_name not in converted
            or not str(module.pathname.value).startswith(f"{DEFAULT_OUTPUT_SUB}|{MASK_SUBDIR}")
        ):
            continue
        managed.append(
            {
                "object": converted[image_name],
                "label_image": image_name,
                "suffix": module.file_name_suffix.value,
                "format": module.file_format.value,
                "reference_image": module.file_image_name.value,
            }
        )
    return managed


def add_masks(pipeline, instantiate_module, objects, ref_image, fmt, report):
    """Add two modules for each object type: one makes a label image, and one saves it.

    ConvertObjectsToImage changes the objects into a 16-bit image: 0 = background, 1 to N = objects.
    SaveImages writes it as masks/<sub-folder of the input>/<reference image name>_<Object>_mask.<ext>.

    Parameters
    ----------
    pipeline : cellprofiler_core.pipeline.Pipeline
        The pipeline to change.
    instantiate_module : callable
        Makes a module from its name (from init_cellprofiler).
    objects : list of str
        The object names, for example ["Nuclei", "Cells"].
    ref_image : str
        The input image whose file name the masks get, for example "DNA".
    fmt : str
        The file format: "tiff", "png" or "npy".
    report : dict
        The report. The function adds each new mask writer to ``report["masks_added"]``.

    Returns
    -------
    list of cellprofiler_core.module.Module
        The new modules (two per object).
    """
    images = set(provider_names(pipeline, "imagegroup"))
    added = []

    # For each object: choose a name for the label image that the pipeline does not use yet,
    # then add the two modules.
    for obj in objects:
        img = f"{PREFIX}_{obj}_labels"
        i = 1
        while img in images:
            img, i = f"{PREFIX}_{obj}_labels_{i}", i + 1
        images.add(img)
        suffix = f"_{obj}_mask"

        # Module 1: objects -> label image (uint16: up to 65,535 objects per image).
        conv = append_module(pipeline, instantiate_module, "ConvertObjectsToImage")
        set_value(conv.object_name, obj, "ConvertObjectsToImage.object_name")
        set_value(conv.image_name, img, "ConvertObjectsToImage.image_name")
        set_value(conv.image_mode, "uint16", "ConvertObjectsToImage.image_mode")

        # Module 2: save the label image with the name of the reference input image plus a suffix.
        save = append_module(pipeline, instantiate_module, "SaveImages")
        set_value(save.save_image_or_figure, "Image", "SaveImages.save_image_or_figure")
        set_value(save.image_name, img, "SaveImages.image_name")
        set_value(save.file_name_method, "From image filename", "SaveImages.file_name_method")
        set_value(save.file_image_name, ref_image, "SaveImages.file_image_name")
        set_value(save.wants_file_name_suffix, True, "SaveImages.wants_file_name_suffix")
        set_value(save.file_name_suffix, suffix, "SaveImages.file_name_suffix")
        set_value(save.file_format, fmt, "SaveImages.file_format")
        if fmt in ("tiff", "png"):
            set_value(save.bit_depth, "16-bit integer", "SaveImages.bit_depth")
        set_value(save.pathname, f"{DEFAULT_OUTPUT_SUB}|{MASK_SUBDIR}", "SaveImages.pathname")

        # Never overwrite a file. If two image sets get the same mask name, CellProfiler stops with an error.
        # Otherwise one mask would replace the other without a message.
        set_value(save.overwrite, False, "SaveImages.overwrite")
        set_value(save.when_to_save, "Every cycle", "SaveImages.when_to_save")
        set_value(save.update_file_names, False, "SaveImages.update_file_names")

        # Copy the sub-folders of the image folder below masks/. Thus plate1/A01.tif and plate2/A01.tif get
        # different mask paths. The workflow runs CellProfiler with -i <image folder>.
        set_value(save.create_subdirectories, True, "SaveImages.create_subdirectories")
        set_value(save.root_dir, "Default Input Folder|", "SaveImages.root_dir")

        added += [conv, save]
        report["masks_added"].append({"object": obj, "label_image": img, "suffix": suffix, "format": fmt})
    return added


def ensure_export(pipeline, instantiate_module, report):
    """Add ExportToSpreadsheet if the pipeline has none.

    Without this module, CellProfiler writes no feature tables.

    Parameters
    ----------
    pipeline : cellprofiler_core.pipeline.Pipeline
        The pipeline to change.
    instantiate_module : callable
        Makes a module from its name (from init_cellprofiler).
    report : dict
        The report. ``report["export_added"]`` becomes True if the function adds the module.

    Returns
    -------
    list of cellprofiler_core.module.Module
        The new module, or an empty list if the pipeline already had one.
    """
    if any(m.module_name == "ExportToSpreadsheet" and is_enabled(m) for m in pipeline.modules()):
        return []
    exp = append_module(pipeline, instantiate_module, "ExportToSpreadsheet")
    set_value(exp.directory, f"{DEFAULT_OUTPUT}|", "ExportToSpreadsheet.directory")
    report["export_added"] = True
    return [exp]


def prepare_export(pipeline, report):
    """Make each ExportToSpreadsheet write the tables in the layout that the merge reads.

    The tables go into the job folder itself, without a file name prefix: Image.csv, Cells.csv, Nuclei.csv,
    Cytoplasm.csv, with the same names in every chunk and run. Each object table gets the image metadata
    (plate, well, site), and each object gets its own file.

    Parameters
    ----------
    pipeline : cellprofiler_core.pipeline.Pipeline
        The pipeline to change.
    report : dict
        The report. Each change goes to ``report["export_changes"]``.
    """
    exports = [m for m in pipeline.modules() if is_enabled(m) and m.module_name == "ExportToSpreadsheet"]
    if len(exports) > 1:
        report["warnings"].append(
            f"{len(exports)} ExportToSpreadsheet modules write into the same folder without a prefix: tables "
            "with the same name replace each other. Keep one ExportToSpreadsheet module."
        )
    for module in exports:
        changes = []

        # Change a setting only if it has another value, and note each change.
        def change(setting, value, label, module=module, changes=changes):
            """Set a setting of the module to a value, and note the change.

            Parameters
            ----------
            setting : cellprofiler_core.setting.Setting
                The setting.
            value : object
                The new value.
            label : str
                The name of the setting in the report.
            module : cellprofiler_core.module.Module
                The ExportToSpreadsheet module.
            changes : list of str
                The changes of this module.
            """
            if setting.value != value:
                changes.append(f"{label}: {setting.value!r} -> {value!r}")
                set_value(setting, value, f"#{module.module_num} ExportToSpreadsheet.{label}")

        change(module.wants_prefix, False, "wants_prefix")
        change(module.directory, f"{DEFAULT_OUTPUT}|", "directory")
        change(module.add_metadata, True, "add_metadata")
        for group in module.object_groups:
            change(group.previous_file, False, f"{group.name.value}.previous_file")
            change(group.wants_automatic_file_name, True, f"{group.name.value}.wants_automatic_file_name")
        if changes:
            report["export_changes"].append(
                {"module": f"#{module.module_num} ExportToSpreadsheet", "changes": changes}
            )


def prepare_cellpose(pipeline, report):
    """Make each RunCellpose module run Cellpose in the Python of the container, without a GPU.

    RunCellpose (a plugin) can start a Docker container for each image. Clusters such as Berzelius have no
    Docker, and the CellProfiler jobs run on CPU nodes. The container of the workflow has Cellpose and its
    models.

    Parameters
    ----------
    pipeline : cellprofiler_core.pipeline.Pipeline
        The pipeline to change.
    report : dict
        The report. Each change goes to ``report["cellpose_changes"]``.
    """
    for module in pipeline.modules():
        if not is_enabled(module) or module.module_name != "RunCellpose":
            continue
        changes = []
        if module.docker_or_python.value != "Python":
            changes.append(f"docker_or_python: {module.docker_or_python.value!r} -> 'Python'")
            set_value(module.docker_or_python, "Python", "RunCellpose.docker_or_python")
        if module.use_gpu.value:
            changes.append("use_gpu: True -> False")
            set_value(module.use_gpu, False, "RunCellpose.use_gpu")
        if changes:
            report["cellpose_changes"].append(
                {"module": f"#{module.module_num} RunCellpose", "changes": changes}
            )


def accept_illum_files(pipeline, report):
    """Make the Images module pass the .npy illumination functions that the workflow adds to the file list.

    "Images only" (the default of the Images module) passes only the file types of Bio-Formats, and .npy is
    not one of them: CellProfiler would drop the functions, and NamesAndTypes would report them as missing.
    The rule becomes: the old rule, or a file that ends with .npy.

    Parameters
    ----------
    pipeline : cellprofiler_core.pipeline.Pipeline
        The pipeline to change.
    report : dict
        The report. Each change goes to ``report["images_filter_changes"]``.
    """
    from cellprofiler_core.constants.modules.images import (
        FILTER_CHOICE_CUSTOM,
        FILTER_CHOICE_IMAGES,
        FILTER_DEFAULT,
    )

    for module in pipeline.modules():
        if not is_enabled(module) or module.module_name != "Images":
            continue
        choice = module.filter_choice.value
        if choice == FILTER_CHOICE_IMAGES:
            old = FILTER_DEFAULT
        elif choice == FILTER_CHOICE_CUSTOM:
            old = module.filter.value_text
        else:
            continue  # "No filtering" passes every file
        if '".npy"' in old:
            continue
        new = f'or ({old}) (file does endwith ".npy")'
        set_value(module.filter_choice, FILTER_CHOICE_CUSTOM, "Images.filter_choice")
        module.filter.value = new
        report["images_filter_changes"].append(
            {"module": f"#{module.module_num} Images", "from": f"{choice}: {old}", "to": f"Custom: {new}"}
        )


def check_illum_pipeline(pipeline, report):
    """Check that an illumination pipeline calculates functions and saves them as .npy at the last cycle.

    Parameters
    ----------
    pipeline : cellprofiler_core.pipeline.Pipeline
        The loaded illumination pipeline.
    report : dict
        The report. ``report["illum_outputs"]`` gets one entry per SaveImages module that saves a .npy file.

    Raises
    ------
    PatchFailure
        If the pipeline has no CorrectIlluminationCalculate, no SaveImages that saves .npy files, or saves
        them before the last cycle.
    """
    modules = [m for m in pipeline.modules() if is_enabled(m)]
    calculations = [m for m in modules if m.module_name == "CorrectIlluminationCalculate"]
    if not calculations:
        raise PatchFailure(
            "The illumination pipeline (--illum_pipeline) has no CorrectIlluminationCalculate module that "
            "is on."
        )
    report["illum_calculations"] = [
        f"#{m.module_num} {m.image_name.value} -> {m.illumination_image_name.value} ({m.each_or_all.value})"
        for m in calculations
    ]

    # Each function must be saved as .npy once, at the last cycle: then it holds the average of all images.
    outputs = []
    for module in modules:
        if module.module_name != "SaveImages" or module.save_image_or_figure.value != "Image":
            continue
        if module.file_format.value != "npy":
            continue
        if module.when_to_save.value != "Last cycle":
            raise PatchFailure(
                f"#{module.module_num} SaveImages saves {module.image_name.value} at "
                f"'{module.when_to_save.value}'. Save illumination functions at the 'Last cycle': only then "
                "they hold all images of the plate."
            )
        single = module.file_name_method.value == "Single name"
        outputs.append(
            {
                "module": f"#{module.module_num} SaveImages",
                "image": module.image_name.value,
                "file_name": module.single_file_name.value if single else None,
            }
        )
    if not outputs:
        raise PatchFailure(
            "The illumination pipeline (--illum_pipeline) has no SaveImages module that saves an image as "
            ".npy. "
            "Save each illumination function with SaveImages: file format npy, at the last cycle."
        )
    report["illum_outputs"] = outputs

    # A function that is calculated but not saved is lost. Only warn: the pipeline may use it otherwise.
    unsaved = sorted({m.illumination_image_name.value for m in calculations} - {o["image"] for o in outputs})
    if unsaved:
        report["warnings"].append(f"Illumination functions calculated but not saved as .npy: {unsaved}")


def patch(pipeline, instantiate_module, args, report):
    """Make all changes to the pipeline, in order.

    Parameters
    ----------
    pipeline : cellprofiler_core.pipeline.Pipeline
        The loaded pipeline. The function changes it in place.
    instantiate_module : callable
        Makes a module from its name (from init_cellprofiler).
    args : argparse.Namespace
        The command-line options (from parse_args).
    report : dict
        The report. Each step writes its changes into it.

    Raises
    ------
    PatchFailure
        If a requested object does not exist, or if no input image exists to name the masks after.
    """

    # 1. Remove what stops a headless run, and keep all outputs in the job folder.
    remove_batch_modules(pipeline, report)
    redirect_outputs(pipeline, report)

    # An illumination pipeline makes no masks and no feature tables (main() checked it already).
    if args.illum:
        return

    # Cellpose runs in the Python of the container (clusters have no Docker), on CPUs.
    prepare_cellpose(pipeline, report)

    # The illumination functions in the file list must pass the filter of the Images module.
    if args.illum_files:
        accept_illum_files(pipeline, report)

    # 2. Find the object types (for example Nuclei, Cells), in the order of the pipeline.
    objects = provider_names(pipeline, "objectgroup")
    report["objects"] = sorted(objects, key=lambda n: objects[n][0])
    added = []

    # 3. Add mask saving for each wanted object type that has no mask writer yet.
    if not args.no_masks:
        wanted = report["objects"]

        # --mask_objects can choose some objects. Each name must exist in the pipeline.
        if args.objects:
            requested = [x.strip() for x in args.objects.split(",") if x.strip()]
            missing = [x for x in requested if x not in objects]
            if missing:
                raise PatchFailure(
                    f"--mask_objects {missing} not produced by this pipeline. Available: {report['objects']}"
                )
            wanted = requested
        managed = managed_mask_writers(pipeline)
        done = [mask["object"] for mask in managed]
        report["masks_already_in_pipeline"] = done
        report["masks_managed"] = list(managed)
        todo = [obj for obj in wanted if obj not in done]

        # The workflow names the masks after the first input image of the pipeline (the reference image).
        if not report["objects"]:
            report["warnings"].append("Pipeline defines no objects: no segmentation masks will be produced.")
        else:
            images = provider_names(pipeline, "imagegroup")
            inputs = sorted((num, name) for name, (num, mods) in images.items() if mods & INPUT_PROVIDERS)
            if not inputs:
                raise PatchFailure(
                    "Could not find an input image (NamesAndTypes/LoadData) to name the mask files after."
                )
            existing_refs = {mask["reference_image"] for mask in managed}
            if len(existing_refs) > 1:
                raise PatchFailure(
                    f"Existing cp-headless mask writers use multiple reference images: {existing_refs}"
                )
            ref_image = next(iter(existing_refs), inputs[0][1])
            report["mask_reference_image"] = ref_image
            if todo:
                added += add_masks(pipeline, instantiate_module, todo, ref_image, args.mask_format, report)
                report["masks_managed"].extend(report["masks_added"])

    # 4. Make sure that CellProfiler writes feature tables, with fixed names and the metadata in every table.
    added += ensure_export(pipeline, instantiate_module, report)
    prepare_export(pipeline, report)

    # 5. Let CellProfiler check the settings of each new module.
    for module in added:  # raises ValidationError if two settings do not agree
        module.test_valid(pipeline)


def write_report(path, report):
    """Write the report as JSON.

    The workflow publishes it as pipeline/patch_report.json.

    Parameters
    ----------
    path : str
        Path of the JSON file.
    report : dict
        The report.
    """
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)


def main():
    """Load, check and change the pipeline. Write the changed pipeline and the report.

    If a step fails, the function stops the program with exit code 1 (with ``fatal``).
    """
    args = parse_args()

    # The report starts empty. Each step below adds to it. fatal() writes it, also when a step fails.
    report = {
        "input": args.input,
        "illum": args.illum,
        "cellprofiler_version": None,
        "pipeline_date_revision": pipeline_revision(args.input),
        "objects": [],
        "masks_added": [],
        "masks_managed": [],
        "masks_already_in_pipeline": [],
        "export_added": False,
        "export_changes": [],
        "cellpose_changes": [],
        "images_filter_changes": [],
        "illum_outputs": [],
        "redirected": [],
        "removed_modules": [],
        "warnings": [],
        "errors": [],
        "unpatched": False,
    }

    def fatal(msg):
        """Write the error into the report, write the report, and stop with exit code 1.

        Parameters
        ----------
        msg : str
            The error message.
        """
        report["errors"].append(msg)
        write_report(args.report, report)
        sys.stderr.write(f"\n[patch_cppipe] ERROR: {msg}\n")
        sys.exit(1)

    try:
        Pipeline, instantiate_module, version = init_cellprofiler(args.plugins_dir)
    except Exception as exc:  # wrong container, or CellProfiler is not installed
        fatal(f"Could not import CellProfiler ({exc}). Check the container or local install.")
    report["cellprofiler_version"] = version

    # Start Java, as `cellprofiler` does. The check of a new SaveImages module asks the Metadata module for
    # its metadata names, and a Metadata module that extracts metadata needs Java for that. Stop Java in
    # `finally`, also when fatal() ends the program: stop_java() from an atexit function hangs the program.
    try:
        from cellprofiler_core.utilities.java import start_java, stop_java

        start_java()
    except Exception as exc:
        fatal(f"CellProfiler could not start Java ({exc}). Check the container or local install.")
    try:
        patch_file(args, report, fatal, Pipeline, instantiate_module, version)
    finally:
        stop_java()


def patch_file(args, report, fatal, Pipeline, instantiate_module, version):
    """Load, check and change the pipeline, and write the changed pipeline and the report.

    Parameters
    ----------
    args : argparse.Namespace
        The command-line options (from parse_args).
    report : dict
        The report. Each step writes into it.
    fatal : callable
        Writes the report with an error and stops the program with exit code 1.
    Pipeline : type
        The CellProfiler Pipeline class (from init_cellprofiler).
    instantiate_module : callable
        Makes a module from its name (from init_cellprofiler).
    version : str
        The CellProfiler version.
    """

    # A pipeline from a newer CellProfiler can load, but can give different results. Warn about it.
    running, saved = version_as_revision(version), report["pipeline_date_revision"]
    if running and saved and saved > running:
        report["warnings"].append(
            f"Pipeline was saved with a newer CellProfiler (DateRevision {saved}) than the one running "
            f"({version}). Use a matching container (--container) if loading or results look wrong."
        )

    try:
        pipeline = load_pipeline(Pipeline, args.input)
    except LoadFailure as exc:
        fatal(str(exc))

    # An illumination pipeline that calculates or saves no functions would give the chunks nothing to apply.
    # This is an error of the pipeline, not of the patch: --allow-unpatched does not skip it.
    if args.illum:
        try:
            check_illum_pipeline(pipeline, report)
        except PatchFailure as exc:
            fatal(str(exc))

    # Do this check before the changes, and also with --allow-unpatched. Chunks of such a pipeline give
    # wrong results without any error.
    report["chunk_unsafe_modules"] = chunk_unsafe_modules(pipeline)
    if args.chunked and report["chunk_unsafe_modules"]:
        fatal(
            "This pipeline must process all image sets in one CellProfiler run, but --chunk_size > 0 "
            "splits them into chunks:\n  - "
            + "\n  - ".join(report["chunk_unsafe_modules"])
            + "\nAn illumination function from all images belongs in the illumination pipeline "
            "(--illum_pipeline): the workflow runs it once per plate. Otherwise run with --chunk_size 0."
        )

    # Change the pipeline and save it, without a file list: the workflow gives each chunk its own list
    # (--file-list). If a change fails, stop, unless the user allowed the original pipeline.
    try:
        patch(pipeline, instantiate_module, args, report)
        with open(args.output, "w", encoding="utf-8") as fh:
            pipeline.dump(fh, save_image_plane_details=False)
    except Exception as exc:
        report["errors"].append(traceback.format_exc())
        if not args.allow_unpatched:
            fatal(f"Patching failed: {exc}. Re-run with --allow_unpatched true to use the pipeline as-is.")
        shutil.copyfile(args.input, args.output)
        report.update(unpatched=True, masks_added=[], masks_managed=[], export_added=False)
        report["warnings"].append(
            "Patching failed; running the ORIGINAL pipeline (masks/features not guaranteed)."
        )

    # Write the report, and show a short summary in the log of the job.
    write_report(args.report, report)
    print(f"[patch_cppipe] CellProfiler {version}; objects: {report['objects'] or 'none'}")
    print(f"[patch_cppipe] masks added for: {[m['object'] for m in report['masks_added']] or 'none'}")
    print(f"[patch_cppipe] ExportToSpreadsheet added: {report['export_added']}")
    for r in report["redirected"]:
        print(f"[patch_cppipe] redirected {r['module']}: {r['from']!r} -> {r['to']!r}")
    for entry in report["export_changes"] + report["cellpose_changes"]:
        print(f"[patch_cppipe] changed {entry['module']}: {'; '.join(entry['changes'])}")
    for entry in report["images_filter_changes"]:
        print(f"[patch_cppipe] changed {entry['module']} filter: {entry['from']!r} -> {entry['to']!r}")
    for output in report["illum_outputs"]:
        print(f"[patch_cppipe] illumination function {output['image']} saved by {output['module']}")
    for w in report["warnings"]:
        print(f"[patch_cppipe] WARNING: {w}", file=sys.stderr)


if __name__ == "__main__":
    main()
