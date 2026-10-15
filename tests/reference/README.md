# Reference feature tables

`MyExpt_Nuclei.csv` and `MyExpt_Cells.csv` are the per-object features of the `test` profile, made on
2026-10-15 with `-profile test,docker` and the pinned official image (CellProfiler 4.2.8, Python 3.8,
NumPy 1.24.4). They keep the key columns and every numeric feature column.

The end-to-end tests (`tests/test_cellprofiler.py`, `tests/test_local_cellprofiler.py`) compare a new run
with these tables. Change them only on purpose, for example for a new CellProfiler version, and write
the reason in CHANGELOG.md.
