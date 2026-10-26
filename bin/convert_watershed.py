#!/usr/bin/env python3
"""One-time tool: convert the supplied Cellpose analysis pipeline to classic watershed segmentation.

This script is not part of the workflow. It made cp-configs/2_analysis.cppipe from the original
Cellpose pipeline. Run it again only to remake that file:

    python bin/convert_watershed.py <cellpose.cppipe> <2_analysis.cppipe>

Data in:  a .cppipe that has two RunCellpose modules and one EnforceObjectsOneToOne module.
Data out: the same pipeline without those three modules. Two modules take their place:
  IdentifyPrimaryObjects    finds nuclei (NucleiPaired) on CorrDNA. Diameter 20-80 px,
                            intensity-based declumping.
  IdentifySecondaryObjects  grows cells (CellsPaired) from those nuclei with a gradient
                            watershed on CellBody (the mean of CorrAGP and CorrER).
All other modules and settings stay the same. The script loads the result again to check it.
"""

import io
import re
from pathlib import Path

from cellprofiler_core.preferences import set_headless

# Tell CellProfiler there is no screen before it loads any modules.
set_headless()
from cellprofiler_core.pipeline import Pipeline
from cellprofiler_core.pipeline.event import LoadException
from cellprofiler.modules.identifyprimaryobjects import IdentifyPrimaryObjects
from cellprofiler.modules.identifysecondaryobjects import IdentifySecondaryObjects


def check_load(pipeline, event):
    """Stop with an error if CellProfiler cannot load a module.

    CellProfiler calls this function for every event while it loads a pipeline.
    """
    if isinstance(event, LoadException):
        raise ValueError(f"{event.module_name}: {event.error}")


def convert(source, destination):
    """Write the watershed version of a Cellpose pipeline, then load it again to check it.

    Args:
        source: the Cellpose .cppipe file.
        destination: the .cppipe file to write.

    Raises:
        ValueError: if the source does not have exactly the three expected Cellpose modules.
    """

    # Split the text into the file header and one part per module. Drop the three Cellpose modules.
    text = Path(source).read_text()
    sections = re.split(r"(?=^\w+:\[module_num:)", text, flags=re.M)
    retained = [
        s
        for s in sections[1:]
        if not s.startswith(("RunCellpose:", "EnforceObjectsOneToOne:"))
    ]
    if len(sections) - 1 - len(retained) != 3:
        raise ValueError(
            "Expected the two supplied RunCellpose modules and one pairing module"
        )

    # Update the module count and the module numbers, then load the shorter pipeline.
    text = re.sub(r"ModuleCount:\d+", f"ModuleCount:{len(retained)}", sections[0])
    text += "".join(
        re.sub(r"module_num:\d+", f"module_num:{i}", s, count=1)
        for i, s in enumerate(retained, 1)
    )
    pipeline = Pipeline()
    pipeline.add_listener(check_load)
    pipeline.load(io.StringIO(text))

    # Nuclei: found on the corrected DNA image, 20-80 px across, touching nuclei split by intensity.
    primary = IdentifyPrimaryObjects()
    primary.x_name.value = "CorrDNA"
    primary.y_name.value = "NucleiPaired"
    primary.use_advanced.value = True
    primary.size_range.value = (20, 80)
    primary.exclude_border_objects.value = False
    primary.unclump_method.value = "Intensity"
    primary.watershed_method.value = "Intensity"
    primary.notes = [
        "Watershed replacement: Otsu nuclei detection, intensity declumping, diameter 20-80 px. Starting range around the former 40 px expectation. Validate for each assay."
    ]

    # Cells: grown from each nucleus over the CellBody image with a gradient watershed.
    secondary = IdentifySecondaryObjects()
    secondary.x_name.value = "NucleiPaired"
    secondary.y_name.value = "CellsPaired"
    secondary.image_name.value = "CellBody"
    secondary.method.value = "Watershed - Gradient"
    secondary.wants_discard_edge.value = False
    secondary.notes = [
        "Nucleus-seeded gradient watershed on the existing mean of CorrAGP and CorrER. Subsequent border filtering is unchanged."
    ]

    # Put the two new modules where the Cellpose modules were, then number all modules again.
    modules = pipeline.modules(False)
    modules[7:7] = [primary, secondary]
    result = Pipeline()
    for i, module in enumerate(modules, 1):
        module.set_module_num(i)
        result.add_module(module)
    with open(destination, "w") as stream:
        result.dump(stream)

    # Load the new file again to prove that CellProfiler accepts it and that Cellpose is gone.
    verify = Pipeline()
    verify.add_listener(check_load)
    verify.load(str(destination))
    assert not any("cellpose" in m.module_name.lower() for m in verify.modules(False))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("destination")
    args = parser.parse_args()
    convert(args.source, args.destination)
