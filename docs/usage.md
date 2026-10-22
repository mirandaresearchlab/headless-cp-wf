# Run on your data

This page tells you how to prepare your images and your two pipelines, and how to start a run.
Do the [tutorial](tutorials/first-run.md) first.

!!! info "Before you start"
    This page assumes that you installed the workflow and ran its test. On a lab workstation, see
    [Installation](getting-started/installation.md). On Berzelius, see [Berzelius: set up](how-to/berzelius-setup.md). To check, open a terminal in the
    folder `headless-cp-wf` and run `nextflow -version`. It must print a version number.

## Prepare the input

You need three things.

**1. An illumination pipeline** (`--illum_pipeline`, for example `1_illumination.cppipe`). It calculates one
illumination function per channel from all images of a plate (CorrectIlluminationCalculate, "All: Across
cycles"), and saves each function as `.npy` with SaveImages at the last cycle. The workflow runs it once per
plate.

**2. An analysis pipeline** (`--pipeline`, for example `2_analysis_cellpose.cppipe`). It loads the functions
with NamesAndTypes, applies them (CorrectIlluminationApply), segments the cells (for example with
RunCellpose), and measures the features. The workflow runs it in chunks of sites.

The PANC1 Cell Painting pipelines are in `cp-configs/` of the repository, ready for the workflow, with a
params file for Berzelius (`cp-configs/berzelius_params.yml`).

Make both in CellProfiler **4.2.8** (the line `DateRevision: 428` at the top of a `.cppipe` file). They must
find their images with the Images, Metadata and NamesAndTypes modules: the workflow gives CellProfiler a list
of files for each job. You do not need to change your pipelines for the cluster: the workflow sets RunCellpose
to Python without a GPU, and prepares ExportToSpreadsheet and the masks. See
[CellProfiler pipelines](reference/pipelines.md) for all requirements and changes.

**3. An image folder with one sub-folder per plate.** The name of the sub-folder is the plate name. The
workflow searches all sub-folders for files with an image extension (`--extensions`). It skips hidden files.
For example:

```text
images/
├── PANC1_P01/
│   ├── A02_s1_x0_y0_Fluorescence_405_nm_Ex.tiff   site 1 of well A02, 405 nm (DNA)
│   ├── A02_s1_x0_y0_Fluorescence_488_nm_Ex.tiff   488 nm (RNA)
│   ├── ...                                        561, 638, 730 nm
│   └── A02_s2_x0_y0_Fluorescence_405_nm_Ex.tiff   site 2 of well A02
└── PANC1_P02/
    └── ...
```

Plate names may have letters, digits, `.`, `_` and `-`. The run stops if a file is directly in the image
folder (it has no plate). If all plates share one folder, set `--plate_regex` to a regular expression whose
first capture group is the plate, for example `'^all/(P\d+)_'`. For more layouts, see
[Prepare your image folder](how-to/format-image-folder.md).

!!! warning "Keep the image folder clean"
    Thumbnails, overlays or old results in the image folder stop the run, because they do not match
    `group_regex`. The output folder must not be in the image folder.

## Group the files of one site

The workflow does not name your channels. Your pipeline does that, in the NamesAndTypes module. See
[Define the channels in your pipeline](how-to/format-image-folder.md#define-the-channels-in-your-pipeline).

A microscope usually saves one file per channel. CellProfiler must get all channel files of a site in the
same job. `--group_regex` is a regular expression for this. The workflow applies it to the path of each file
in the image folder. The parts in round brackets make the name of the image set. Files with the same name
belong to the same image set.

| File names | `--group_regex` |
| --- | --- |
| `A02_s1_x0_y0_Fluorescence_405_nm_Ex.tiff` (PANC1 Cell Painting) | `'^(.+?_s\d+)_x'` |
| One channel: each file is one image set | `'^(.+)$'` |
| `A01_s1_w1.tif`, `A01_s1_w2.tif` (MetaXpress) | `'^(.+?_s\d+)_w\d'` |
| `r01c01f01p01-ch1sk1fk1fl1.tiff` (Opera, Operetta) | `'(r\d+c\d+f\d+p\d+)-ch'` |

The workflow then checks the image sets of each plate before CellProfiler starts. Every file must match the
pattern, and every image set must have the same number of files. If a check fails, the run stops and names the
plate and examples. See [Data checks and design](explanation/design.md).

To test your pattern before a large run, run the workflow with `-stub-run`. It makes the checks and starts no
CellProfiler job. See [Check the folder before a large run](how-to/format-image-folder.md#check-the-folder-before-a-large-run).

## Choose the chunk size, the cores and the memory

`--chunk_size` is the number of sites (image sets) in one analysis job. The default is 50 sites (250 files with
5 channels). A chunk never holds sites of two plates; the last chunk of a plate may be smaller. On a cluster,
choose a size that gives jobs of 15 to 60 minutes, see
[Choose the chunk size](how-to/berzelius-batch.md#choose-the-chunk-size).

| Parameter | Default | Meaning |
| --- | --- | --- |
| `--segmentation_cpus` | 2 | Cores of one analysis chunk. Cellpose uses exactly these cores. Raise it (for example to 4) if Cellpose is slow. |
| `--memory_per_cpu` | 4.GB (Berzelius: 7.GB) | Memory per core of a chunk: 8 GB at 2 cores |
| `--total_cpus` | 8 (Slurm: 200, Berzelius: 64) | The most cores that the whole run uses at once, for all plates. Jobs that do not fit wait. |
| `--total_memory` | all memory | On a workstation: the most memory of all running jobs together |
| `--max_cpus`, `--max_memory`, `--max_time` | 16, 64.GB, 48.h | The most that one job can get (also after a new try) |

The log shows how many chunks can run at once, and the chunks, cores and memory of each plate. See
[Resources](reference/resources.md).

## Containers and plugins

- The CellProfiler jobs run in `--container`. The default is the official CellProfiler 4.2.8 image, which has
  **no Cellpose**. For a pipeline with RunCellpose, set `--container` to the Cellpose image
  (`containers/cellprofiler-cellpose`: Cellpose 3.1.1.2, CPU PyTorch, the `nuclei` and `cyto3` models). The
  workflow stops at once if a pipeline with RunCellpose would run in the official image.
- See
  [`containers/README.md`](https://github.com/mirandaresearchlab/headless-cp-wf/blob/main/containers/README.md)
  for how to build and publish the Cellpose image.
- The plugins come from `cp-plugins/` of the repository (`runcellpose.py`, `enforceobjectsonetoone.py`). Set
  `--plugins_dir` for another folder. The workflow stops if a pipeline uses a plugin that the folder lacks.

## Start the run

```bash
nextflow run . -profile docker \
    --illum_pipeline /path/to/1_illumination.cppipe \
    --pipeline       /path/to/2_analysis_cellpose.cppipe \
    --input_dir      /path/to/images \
    --outdir         /path/to/results \
    --group_regex    '^(.+?_s\d+)_x' \
    --container      <the Cellpose image> \
    --total_cpus 8 --max_memory '32.GB'
```

Set `--total_cpus`, `--total_memory` and `--max_memory` to the size of your computer.

You can also keep the parameters in a file and give it with `-params-file`. This keeps a record of the run:

```yaml title="params.yml"
illum_pipeline: /data/exp1/1_illumination.cppipe
pipeline: /data/exp1/2_analysis_cellpose.cppipe
input_dir: /data/exp1/images
outdir: /data/exp1/results
group_regex: '^(.+?_s\d+)_x'
required_metadata: Plate,Well,Site
total_cpus: 8
max_memory: 32.GB
```

```bash
nextflow run . -profile docker -params-file params.yml
```

To use the illumination functions of an earlier run, give its output folder with `--illum_dir` instead of
`--illum_pipeline` (the workflow looks in `<illum_dir>/<plate>/illum/`).

All parameters are in the [parameter reference](reference/parameters.md).

## Profiles

Choose one or more profiles with `-profile`, separated by commas.

| Profile | Use when |
| --- | --- |
| `test` | You want to run the included test data. Combine it with one of the profiles below. |
| `local` | CellProfiler runs from your conda environment on the workstation, without a container. See [Run without Docker](how-to/run-without-docker.md). |
| `docker` | CellProfiler runs in a container with Docker. See [Run with Docker](how-to/run-with-docker.md). |
| `berzelius` | You run on Berzelius. It uses Slurm and Apptainer. See [Berzelius: set up](how-to/berzelius-setup.md). |

The profiles `slurm`, `apptainer` and `singularity` also exist. The `berzelius` profile builds on the `slurm`
settings and turns on Apptainer itself. We support and test these settings only as parts of `berzelius`.

## Continue a run

Add `-resume` to continue a run that stopped. Nextflow runs only the jobs that changed or failed, and uses
the results of the other jobs. Start the run from the same folder, because Nextflow keeps its cache in
`.nextflow/` there.

## Metadata for profiling

The workflow puts the plate (the plate folder) into `Metadata_Plate` of every row. Well and site come from
the Metadata module of your pipeline (for example `Well` and `Site` from the file name). Add
`--required_metadata Plate,Well,Site`: the workflow then stops if a value is missing or empty, or if two image
sets have the same values. With several plates, the log recommends it.

## Next steps

- What each result file contains: [Output](output.md).
- Problems: [Troubleshooting](how-to/troubleshooting.md).
