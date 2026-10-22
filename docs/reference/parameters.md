# Parameters

<!-- GENERATED from nextflow_schema.json by gen_nextflow_params.py: edit the schema, not this page. -->

Run CellProfiler headless on microscope images, plate by plate: illumination functions once per plate, the analysis in chunks, then one single-cell table of all plates.

Pass parameters on the command line (`--name value`) or in a file with `-params-file params.yml`.

## Input and output

The two CellProfiler pipelines, the image folder, and where the results go.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--pipeline` **(required)** | string<br><small>file-path</small> |  | The analysis pipeline (segmentation and features): a .cppipe or .cpproj file. It runs in chunks.<br><small>Make it in the CellProfiler program. It must come from the CellProfiler version of the container (DateRevision 428 = 4.2.8).</small> |
| `--illum_pipeline` | string<br><small>file-path</small> |  | The illumination pipeline: it calculates one illumination function per channel from all images of a plate. It runs once per plate.<br><small>It needs CorrectIlluminationCalculate and a SaveImages module per function that saves .npy at the last cycle. The analysis pipeline loads the functions with NamesAndTypes (for example files that start with IllumDNA). Do not set it together with illum_dir.</small> |
| `--illum_dir` | string<br><small>directory-path</small> |  | Reuse illumination functions instead of calculating them: one sub-folder per plate with its .npy files.<br><small>The workflow looks in <illum_dir>/<plate>/illum/ (the results of an earlier run) and in <illum_dir>/<plate>/. Each plate needs one file per channel.</small> |
| `--input_dir` **(required)** | string<br><small>directory-path</small> |  | The image folder, with one sub-folder per plate. The workflow also searches deeper sub-folders, and skips hidden files. |
| `--outdir` | string<br><small>directory-path</small> | `results` | The output folder. It must not be inside input_dir. |
| `--publish_mode` | string<br><small>one of `copy`, `symlink`, `link`</small> | `copy` | How the results go to outdir.<br><small>copy keeps the results when you remove the work folder. symlink and link use less space, but need the work folder.</small> |
| `--gzip_features` | boolean | `false` | Write the merged tables as .csv.gz. |
| `--merge_all_plates` | boolean | `true` | Merge the tables of all plates into one table per object type (cellprofiler_tables/). false makes one table per plate (<plate>/cellprofiler_tables/). |
| `--check_compartments` | boolean | `true` | Stop the merge if the Image, Cells, Nuclei or Cytoplasm table is missing, or a column that joins them: ImageNumber, ObjectNumber, Number_Object_Number, Parent_Cells and Parent_Nuclei (Cytoplasm), Metadata_Plate, Metadata_Well and Metadata_Site.<br><small>With these tables and columns, each cytoplasm object can be joined to its cell, its nucleus and its image in one row per cell. The pipeline must make the objects Cells, Nuclei and Cytoplasm (IdentifyTertiaryObjects), and the Metadata module must make Well and Site. It also checks that no plate, well and site occur twice. Set it to false for other pipelines.</small> |
| `--extensions` | string | `tif,tiff,png,jpg,jpeg,bmp,c01,dib,flex,czi,nd2,lif,lsm,oib,oif,ims,zvi` | The file extensions of the images, separated by commas. Upper case and lower case are the same. |
| `--plate_regex` | string |  | A regular expression that finds the plate of each file. Empty = the first folder below input_dir is the plate.<br><small>The workflow applies it to each file path relative to input_dir and takes capture group 1. Plate names may have letters, digits, '.', '_' and '-'.</small> |

## Image sets and chunks

How the workflow groups files into image sets (one site, all channels), divides them into chunks, and checks them.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--group_regex` | string |  | A regular expression that finds the files of one image set.<br><small>The workflow applies it to each file path relative to input_dir. The capture groups make the name of the image set. Example: '^(.+?_s\d+)_w\d' for A01_s1_w1.tif and A01_s1_w2.tif.</small> |
| `--chunk_size` | integer<br><small>≥ 0</small> | `50` | The number of image sets (sites) per analysis job. The last chunk of a plate may be smaller. 0 puts all image sets of a plate into one job.<br><small>A chunk never holds sites of two plates. On a cluster, choose a size that gives jobs of 15 to 60 minutes.</small> |
| `--strict_image_count` | boolean | `true` | Stop if CellProfiler makes a different number of image sets than the workflow predicted.<br><small>A difference usually means that the channels of a site were split between two chunks. false gives a warning only.</small> |
| `--allow_incomplete_sets` | boolean | `false` | Continue with a warning when a file does not match group_regex or an image set has a missing channel.<br><small>Each file that does not match then becomes an image set of its own.</small> |
| `--required_metadata` | string<br><small>pattern `^\s*\w+(\s*,\s*\w+)*\s*$`</small> |  | Metadata names that each image set must have, unique, for example Plate,Well,Site.<br><small>Use the names that the Metadata module of your pipeline makes. The workflow stops if a value is missing or empty, or if two image sets have the same values.</small> |

## Masks and CellProfiler

The segmentation masks that the workflow adds, and how CellProfiler runs.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--save_masks` | boolean | `true` | Save a mask (16-bit label image) for each object type of the pipeline. |
| `--mask_objects` | string | `Nuclei,Cells,Cytoplasm` | Save masks for these objects, separated by commas. Empty = all objects of the pipeline.<br><small>A chunk fails if a site misses one of its masks. The masks of a plate go to <outdir>/<plate>/masks/.</small> |
| `--mask_format` | string<br><small>one of `tiff`, `png`, `npy`</small> | `tiff` | The file format of the masks. tiff and png are 16-bit images. npy holds the raw label numbers. |
| `--allow_unpatched` | boolean | `false` | If the preparation of the pipeline fails, run the original pipeline. Masks and tables are then not certain. |
| `--container` | string | `cellprofiler/cellprofiler@sha256:fec440caa2b44edf80f9bd440a3d8c6b214d72437332ad2586a32d79e2eae2a4` | The CellProfiler container image. Use the CellProfiler version of your pipeline.<br><small>The default is pinned by its digest, so each run uses the same image. It has no Cellpose: for a pipeline with RunCellpose, use the Cellpose image (containers/cellprofiler-cellpose).</small> |
| `--plugins_dir` | string<br><small>directory-path</small> | `${projectDir}/cp-plugins` | A folder with CellProfiler plugins. The default is cp-plugins/ of the repository (runcellpose.py, enforceobjectsonetoone.py).<br><small>The workflow stops if the pipeline uses RunCellpose or EnforceObjectsOneToOne and the folder lacks its file.</small> |
| `--cellprofiler_args` | string | `""` | More options for the cellprofiler command, for example '--conserve-memory True'. |

## Computer resources

The cores and memory of the analysis chunks and of the whole run, and the maximum resources of one job. A new try after a memory or time error asks for more, up to the maximum.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--segmentation_cpus` | integer<br><small>≥ 1</small> | `2` | The number of cores of one analysis chunk (Cellpose and features). Cellpose uses exactly these cores.<br><small>Raise it later, for example to 4, if Cellpose is the slow part of a chunk.</small> |
| `--memory_per_cpu` | string<br><small>pattern `^\d+(\.\d+)?\.?\s*(K\\|M\\|G\\|T)?B$`</small> | `4.GB` | The memory per core of one analysis chunk: 4.GB x 2 cores = 8 GB. The berzelius profile uses 7.GB.<br><small>A starting value: after a test run, set it from trace.txt (peak_rss + 25 %).</small> |
| `--total_cpus` | integer<br><small>≥ 1</small> | `8` | The most cores that the whole run uses at once, for the ILLUM and analysis jobs of all plates. Jobs that do not fit wait.<br><small>Local runs: Nextflow starts a job only when its cores are free. Slurm and Berzelius: at most total_cpus / segmentation_cpus jobs are queued or running. The slurm profile uses 200, the berzelius profile 64.</small> |
| `--total_memory` | string<br><small>pattern `^\d+(\.\d+)?\.?\s*(K\\|M\\|G\\|T)?B$`</small> |  | Local runs: the most memory that all running jobs use together, for example 64.GB. Empty = all memory of the computer. |
| `--max_cpus` | integer<br><small>≥ 1</small> | `16` | The maximum number of CPU cores of one job. Set it to the size of your computer or node. |
| `--max_memory` | string<br><small>pattern `^\d+(\.\d+)?\.?\s*(K\\|M\\|G\\|T)?B$`</small> | `64.GB` | The maximum memory of one job, for example 32.GB. Set it to the size of your computer or node. |
| `--max_time` | string | `48.h` | The maximum time of one job, for example 48.h. |

## Clusters and containers

Settings for the slurm and berzelius profiles, and for Apptainer or Singularity.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--slurm_account` | string |  | The Slurm account of each job. Most clusters need one. Required for the berzelius profile. |
| `--slurm_partition` | string |  | The Slurm partition. Empty = the default partition of the cluster.<br><small>For the berzelius profile, use berzelius-cpu (Ampere) or berzelius-hopper-cpu (Hopper).</small> |
| `--slurm_scratch` | string |  | A folder on the local disk of the node for each job, for example '$TMPDIR'.<br><small>Set it only if the nodes have a local disk. The berzelius profile uses /scratch/local.</small> |
| `--slurm_cluster_options` | string |  | More sbatch options for each job, for example '--qos=normal'. |
| `--container_cache` | string<br><small>directory-path</small> |  | A shared folder for Apptainer or Singularity images. Do not use your home folder. |

