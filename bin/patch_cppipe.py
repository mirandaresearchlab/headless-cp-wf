#!/usr/bin/env python3
"""
Make a CellProfiler pipeline safe for headless, chunked execution.

What it does (everything is recorded in a JSON report):
  * fails fast if the CellProfiler in this environment cannot load the pipeline
    (missing plugin, pipeline saved by a newer CellProfiler, ...);
  * removes CreateBatchFiles (it stops a headless run after writing a batch file);
  * redirects output modules that write to an absolute path ("Elsewhere...") or into
    the input folder, so every chunk writes into its own task directory and nothing
    is ever written back into your raw-image folder;
  * adds ConvertObjectsToImage (uint16 labels) + SaveImages for every object set
    that is not already saved, so you always get segmentation masks;
  * adds ExportToSpreadsheet if the pipeline has none, so you always get features.

Exit codes: 0 = ok, 1 = cannot load / cannot patch (and --allow-unpatched not set).
"""

import argparse
import json
import shutil
import sys
import traceback

OUTPUT_MODULES = {
    "SaveImages",
    "ExportToSpreadsheet",
    "ExportToDatabase",
    "SaveCroppedObjects",
}
INPUT_PROVIDERS = {"NamesAndTypes", "LoadData", "LoadImages"}
DEFAULT_OUTPUT = "Default Output Folder"
DEFAULT_OUTPUT_SUB = "Default Output Folder sub-folder"
UNSAFE_DIR_CHOICES = {
    "Elsewhere...",
    "Default Input Folder",
    "Default Input Folder sub-folder",
}
MASK_SUBDIR = "masks"
PREFIX = "CPNF"  # marks names we add, keeps re-patching idempotent


class LoadFailure(RuntimeError):
    pass


class PatchFailure(RuntimeError):
    pass


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", required=True, help=".cppipe or .cpproj file")
    p.add_argument("--output", required=True, help="patched .cppipe to write")
    p.add_argument("--report", required=True, help="JSON report to write")
    p.add_argument("--mask-format", default="tiff", choices=["tiff", "png", "npy"])
    p.add_argument("--objects", default=None, help="comma-separated object names to save (default: all)")
    p.add_argument("--no-masks", action="store_true", help="do not inject mask saving")
    p.add_argument("--plugins-dir", default=None)
    p.add_argument(
        "--allow-unpatched",
        action="store_true",
        help="if patching fails, fall back to the original pipeline instead of failing",
    )
    return p.parse_args()


# --------------------------------------------------------------------------- setup
def init_cellprofiler(plugins_dir):
    from cellprofiler_core.preferences import set_headless

    set_headless()
    if plugins_dir:
        from cellprofiler_core.preferences import set_plugin_directory

        try:
            set_plugin_directory(plugins_dir, globally=False)
        except TypeError:  # older signature
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
    """'4.2.8' -> 428, matching the DateRevision field written into .cppipe files."""
    parts = str(version).split(".")[:3]
    if len(parts) == 3 and all(x.isdigit() for x in parts):
        return int(parts[0]) * 100 + int(parts[1]) * 10 + int(parts[2])
    return None


def pipeline_revision(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for _ in range(10):
                line = fh.readline()
                if line.startswith("DateRevision:"):
                    return int(line.split(":", 1)[1].strip())
    except (OSError, ValueError):
        pass
    return None  # .cpproj (HDF5) or unusual header


def load_pipeline(Pipeline, path):
    pipeline = Pipeline()
    problems = []

    def listener(_caller, event):
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
    return getattr(module, "enabled", True)


def set_value(setting, value, label):
    # Only Choice settings carry a fixed list of allowed values.
    if type(setting).__name__ == "Choice" and value not in setting.choices:
        raise PatchFailure(f"{label}: '{value}' is not one of {list(setting.choices)}")
    setting.value = value


def append_module(pipeline, instantiate_module, name):
    module = instantiate_module(name)
    module.set_module_num(len(pipeline.modules()) + 1)
    pipeline.add_module(module)
    return module


def provider_names(pipeline, group):
    providers = pipeline.get_provider_dictionary(group)
    out = {}
    for name, provs in providers.items():
        nums = [m.module_num for m, _ in provs if is_enabled(m)]
        if nums:
            out[name] = (min(nums), {m.module_name for m, _ in provs})
    return out


# --------------------------------------------------------------------------- patch steps
def remove_batch_modules(pipeline, report):
    for module in reversed(list(pipeline.modules())):
        if module.module_name == "CreateBatchFiles":
            pipeline.remove_module(module.module_num)
            report["removed_modules"].append("CreateBatchFiles")


def redirect_outputs(pipeline, report):
    for module in pipeline.modules():
        if module.module_name not in OUTPUT_MODULES or not is_enabled(module):
            continue
        # SaveImages.root_dir describes where *input* images live (for mirroring
        # sub-folders); it must keep pointing at the input side.
        input_side = {id(getattr(module, "root_dir", None))}
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
        if module.module_name == "SaveImages" and module.file_name_method.value == "Sequential numbers":
            report["warnings"].append(
                f"#{module.module_num} SaveImages uses 'Sequential numbers'; numbering restarts in every "
                "chunk, so files from different chunks will share names. Prefer 'From image filename'."
            )


def managed_mask_writers(pipeline):
    """Return canonical mask writers previously injected by cp-headless."""
    converted = {}
    for m in pipeline.modules():
        if is_enabled(m) and m.module_name == "ConvertObjectsToImage":
            converted[m.image_name.value] = m.object_name.value

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
    images = set(provider_names(pipeline, "imagegroup"))
    added = []
    for obj in objects:
        img = f"{PREFIX}_{obj}_labels"
        i = 1
        while img in images:
            img, i = f"{PREFIX}_{obj}_labels_{i}", i + 1
        images.add(img)
        suffix = f"_{obj}_mask"

        conv = append_module(pipeline, instantiate_module, "ConvertObjectsToImage")
        set_value(conv.object_name, obj, "ConvertObjectsToImage.object_name")
        set_value(conv.image_name, img, "ConvertObjectsToImage.image_name")
        set_value(conv.image_mode, "uint16", "ConvertObjectsToImage.image_mode")

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
        # Never overwrite: two image sets mapping to the same mask file must fail loudly,
        # not silently lose a mask.
        set_value(save.overwrite, False, "SaveImages.overwrite")
        set_value(save.when_to_save, "Every cycle", "SaveImages.when_to_save")
        set_value(save.update_file_names, False, "SaveImages.update_file_names")
        # Mirror the input folder tree under masks/ so plate1/A01.tif and plate2/A01.tif
        # do not collide. The workflow runs CellProfiler with -i <input root>.
        set_value(save.create_subdirectories, True, "SaveImages.create_subdirectories")
        set_value(save.root_dir, "Default Input Folder|", "SaveImages.root_dir")

        added += [conv, save]
        report["masks_added"].append({"object": obj, "label_image": img, "suffix": suffix, "format": fmt})
    return added


def ensure_export(pipeline, instantiate_module, report):
    if any(m.module_name == "ExportToSpreadsheet" and is_enabled(m) for m in pipeline.modules()):
        return []
    exp = append_module(pipeline, instantiate_module, "ExportToSpreadsheet")
    set_value(exp.directory, f"{DEFAULT_OUTPUT}|", "ExportToSpreadsheet.directory")
    report["export_added"] = True
    return [exp]


def patch(pipeline, instantiate_module, args, report):
    remove_batch_modules(pipeline, report)
    redirect_outputs(pipeline, report)

    objects = provider_names(pipeline, "objectgroup")
    report["objects"] = sorted(objects, key=lambda n: objects[n][0])
    added = []

    if not args.no_masks:
        wanted = report["objects"]
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

    added += ensure_export(pipeline, instantiate_module, report)

    for module in added:  # raises ValidationError if a setting is inconsistent
        module.test_valid(pipeline)


def write_report(path, report):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)


def main():
    args = parse_args()
    report = {
        "input": args.input,
        "cellprofiler_version": None,
        "pipeline_date_revision": pipeline_revision(args.input),
        "objects": [],
        "masks_added": [],
        "masks_managed": [],
        "masks_already_in_pipeline": [],
        "export_added": False,
        "redirected": [],
        "removed_modules": [],
        "warnings": [],
        "errors": [],
        "unpatched": False,
    }

    def fatal(msg):
        report["errors"].append(msg)
        write_report(args.report, report)
        sys.stderr.write(f"\n[patch_cppipe] ERROR: {msg}\n")
        sys.exit(1)

    try:
        Pipeline, instantiate_module, version = init_cellprofiler(args.plugins_dir)
    except Exception as exc:  # wrong container / environment
        fatal(f"Could not import CellProfiler ({exc}). Check the container or local install.")
    report["cellprofiler_version"] = version

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

    try:
        patch(pipeline, instantiate_module, args, report)
        with open(args.output, "w", encoding="utf-8") as fh:
            # Never embed a file list: the workflow supplies one per chunk via --file-list.
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

    write_report(args.report, report)
    print(f"[patch_cppipe] CellProfiler {version}; objects: {report['objects'] or 'none'}")
    print(f"[patch_cppipe] masks added for: {[m['object'] for m in report['masks_added']] or 'none'}")
    print(f"[patch_cppipe] ExportToSpreadsheet added: {report['export_added']}")
    for r in report["redirected"]:
        print(f"[patch_cppipe] redirected {r['module']}: {r['from']!r} -> {r['to']!r}")
    for w in report["warnings"]:
        print(f"[patch_cppipe] WARNING: {w}", file=sys.stderr)


if __name__ == "__main__":
    main()
