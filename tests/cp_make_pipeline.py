"""Write a test pipeline: tests/test.cppipe plus one extra module.

It runs inside the CellProfiler container (see tests/test_cellprofiler.py), because it uses the
CellProfiler API to make a valid pipeline file.

Examples
--------
python3 cp_make_pipeline.py SOURCE.cppipe OUTPUT.cppipe MODULE [attribute=value ...]

python3 cp_make_pipeline.py test.cppipe out.cppipe TrackObjects
python3 cp_make_pipeline.py test.cppipe out.cppipe Groups wants_groups=True
"""

import sys

from cellprofiler_core.pipeline import Pipeline
from cellprofiler_core.preferences import set_headless
from cellprofiler_core.utilities.core.modules import fill_modules, instantiate_module


def main(source, output, module_name, *assignments):
    """Load the source pipeline, add the module with its settings at the end, and save the result.

    Parameters
    ----------
    source : str
        The pipeline to start from.
    output : str
        Path of the new pipeline file.
    module_name : str
        The CellProfiler module to add, for example "TrackObjects".
    *assignments : str
        Settings of the new module as "attribute=value". "True" and "False" become booleans.
    """
    set_headless()
    fill_modules()
    pipeline = Pipeline()
    pipeline.load(source)
    module = instantiate_module(module_name)
    module.set_module_num(len(pipeline.modules()) + 1)
    pipeline.add_module(module)

    # "each_or_all=All: Across cycles" -> set the setting each_or_all. "True"/"False" become booleans.
    for assignment in assignments:
        attribute, _, value = assignment.partition("=")
        setting = getattr(module, attribute)
        setting.value = {"True": True, "False": False}.get(value, value)
    with open(output, "w", encoding="utf-8") as handle:
        pipeline.dump(handle, save_image_plane_details=False)


if __name__ == "__main__":
    main(*sys.argv[1:])
