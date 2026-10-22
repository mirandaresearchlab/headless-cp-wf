# PANC1 Cell Painting pipelines

The two CellProfiler 4.2.8 pipelines of the PANC1 Cell Painting screen, ready for the workflow, and a params
file for Berzelius.

| File | Parameter | What it does |
| --- | --- | --- |
| `1_illumination.cppipe` | `--illum_pipeline` | One illumination function per channel from all images of a plate (CorrectIlluminationCalculate, "All: Across cycles", median filter 500). SaveImages writes `IllumDNA.npy`, `IllumRNA.npy`, `IllumAGP.npy`, `IllumMito.npy`, `IllumER.npy` at the last cycle. |
| `2_analysis_cellpose.cppipe` | `--pipeline` | Applies the functions, segments nuclei (Cellpose `nuclei`, diameter 40) and cells (Cellpose `cyto3`, diameter 90), pairs them one to one, makes the cytoplasm, and measures size, shape, intensity, colocalization, granularity, texture, radial distribution and neighbors. |
| `berzelius_params.yml` | `-params-file` | The parameters of a run on Berzelius with these pipelines. Replace each `<...>`. |

Channels: 405 nm = DNA, 488 nm = RNA, 561 nm = AGP, 638 nm = Mito, 730 nm = ER. File names:
`A02_s1_x0_y0_Fluorescence_405_nm_Ex.tiff`, in one folder per plate. Image sets are matched by Well and Site.

## Changes for the workflow

`1_illumination.cppipe` is the pipeline of the CellProfiler program, unchanged.

`2_analysis_cellpose.cppipe` was changed with the CellProfiler API (2026-10-22):

1. **RunCellpose** (both modules): "Python" instead of "Docker", and "Use GPU: No". Berzelius has no Docker,
   and the jobs run on CPU nodes. The Cellpose image of the workflow has Cellpose 3.1.1.2 and both models.
2. **No own mask modules.** The 3 ConvertObjectsToImage and 3 SaveImages modules for the Nuclei, Cells and
   Cytoplasm masks are removed. The workflow adds its own mask writers (`--mask_objects
   Nuclei,Cells,Cytoplasm`, the default) and checks that every site has its 3 masks.
3. **Plate from the folder name.** The Metadata module has a second rule: `Plate` from the name of the folder
   of each `.tif` or `.tiff` file. The workflow checks that it is the plate folder in every row.

The workflow makes more changes when it runs (in `results/pipeline/patched.cppipe`): ExportToSpreadsheet
without a file name prefix, into the job folder; the mask writers. See docs/reference/pipelines.md.

The Images module already passes the `.npy` illumination functions (custom rule "or ... file does endwith
.npy"), and NamesAndTypes assigns them by name (`IllumDNA` ... `IllumER`, type "Illumination function").

## Before a large run

- Check the segmentation on 3 or 4 sites in the CellProfiler program (Test Mode): the Cellpose thresholds
  have not been checked against these images yet.
- Run one plate first, and set the memory and the chunk size from `pipeline_info/trace.txt`.
