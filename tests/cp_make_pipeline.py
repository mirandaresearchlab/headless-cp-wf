"""Write a test pipeline: tests/test.cppipe plus one extra module (runs inside the CellProfiler container).

Usage: python3 cp_make_pipeline.py SOURCE.cppipe OUTPUT.cppipe MODULE [attribute=value ...]
"""

import sys

from cellprofiler_core.pipeline import Pipeline
from cellprofiler_core.preferences import set_headless
from cellprofiler_core.utilities.core.modules import fill_modules, instantiate_module


def main(source, output, module_name, *assignments):
    set_headless()
    fill_modules()
    pipeline = Pipeline()
    pipeline.load(source)
    module = instantiate_module(module_name)
    module.set_module_num(len(pipeline.modules()) + 1)
    pipeline.add_module(module)
    for assignment in assignments:
        attribute, _, value = assignment.partition("=")
        setting = getattr(module, attribute)
        setting.value = {"True": True, "False": False}.get(value, value)
    with open(output, "w", encoding="utf-8") as handle:
        pipeline.dump(handle, save_image_plane_details=False)


if __name__ == "__main__":
    main(*sys.argv[1:])
