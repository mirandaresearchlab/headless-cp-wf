# CellProfiler plugins

The workflow gives this folder to CellProfiler (`--plugins-directory`) in every job. It is the default of
`--plugins_dir`. The workflow stops before any job starts if a pipeline uses one of these modules and the
folder lacks its file.

| File | Module | Used for |
| --- | --- | --- |
| `runcellpose.py` | RunCellpose | Segmentation with Cellpose (nuclei, cells) |
| `enforceobjectsonetoone.py` | EnforceObjectsOneToOne | Exactly one nucleus per cell |

## Source

Both files are unchanged copies from
[CellProfiler/CellProfiler-plugins](https://github.com/CellProfiler/CellProfiler-plugins), folder
`active_plugins/`, at commit
[`5aaa4e54513173438b50b8e4b33ad6a592b35df0`](https://github.com/CellProfiler/CellProfiler-plugins/tree/5aaa4e54513173438b50b8e4b33ad6a592b35df0/active_plugins)
(2026-09-30). The git blob hashes of both files match that commit:

| File | git blob hash |
| --- | --- |
| `runcellpose.py` | `3734d98ca755ea7df1de67485b6ea1ec6c8a6a00` |
| `enforceobjectsonetoone.py` | `fdb815183693492f345922ca92175fbfc65d7d51` |

To check: `git hash-object cp-plugins/runcellpose.py`.

## Notes

- RunCellpose runs Cellpose in a Docker container or in the Python of CellProfiler. Clusters such as
  Berzelius have no Docker, so the patch step of the workflow sets every RunCellpose module to **Python**
  and **Use GPU: No**. Cellpose 3.1.1.2, CPU PyTorch and the `nuclei` and `cyto3` models are in the
  Cellpose image (`containers/cellprofiler-cellpose`).
- To update a plugin: copy the new file from the same folder of CellProfiler-plugins, write the new commit
  and blob hashes into this file, rebuild the Cellpose image (it copies this folder), and run the tests.
