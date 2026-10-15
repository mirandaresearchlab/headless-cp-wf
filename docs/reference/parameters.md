# Parameters

<!-- GENERATED from nextflow_schema.json by gen_nextflow_params.py: edit the schema, not this page. -->

Run a CellProfiler pipeline headless on a folder of microscope images, in chunks, and merge the feature tables and masks.

Pass parameters on the command line (`--name value`) or in a file with `-params-file params.yml`.

## Input and output

The CellProfiler pipeline, the image folder, and where the results go.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--pipeline` **(required)** | string<br><small>file-path</small> |  | The CellProfiler pipeline: a .cppipe or .cpproj file.<br><small>Make it in the CellProfiler program. It must come from the CellProfiler version of the container (DateRevision 428 = 4.2.8).</small> |
| `--input_dir` **(required)** | string<br><small>directory-path</small> |  | The image folder. The workflow also searches its sub-folders, and skips hidden files. |
| `--outdir` | string<br><small>directory-path</small> | `results` | The output folder. It must not be inside input_dir. |
| `--publish_mode` | string<br><small>one of `copy`, `symlink`, `link`</small> | `copy` | How the results go to outdir.<br><small>copy keeps the results when you remove the work folder. symlink and link use less space, but need the work folder.</small> |
| `--gzip_features` | boolean | `false` | Write the merged tables as .csv.gz. |
| `--extensions` | string | `tif,tiff,png,jpg,jpeg,bmp,c01,dib,flex,czi,nd2,lif,lsm,oib,oif,ims,zvi` | The file extensions of the images, separated by commas. Upper case and lower case are the same. |

## Image sets and chunks

How the workflow groups files into image sets (one site, all channels), divides them into chunks, and checks them.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--group_regex` | string |  | A regular expression that finds the files of one image set.<br><small>The workflow applies it to each file path relative to input_dir. The capture groups make the name of the image set. Example: '^(.+?_s\d+)_w\d' for A01_s1_w1.tif and A01_s1_w2.tif.</small> |
| `--chunk_size` | integer<br><small>≥ 0</small> | `0` | The number of image sets per CellProfiler job. 0 puts all image sets into one job.<br><small>On a cluster, choose a size that gives jobs of 15 to 60 minutes.</small> |
| `--strict_image_count` | boolean | `true` | Stop if CellProfiler makes a different number of image sets than the workflow predicted.<br><small>A difference usually means that the channels of a site were split between two chunks. false gives a warning only.</small> |
| `--allow_incomplete_sets` | boolean | `false` | Continue with a warning when a file does not match group_regex or an image set has a missing channel.<br><small>Each file that does not match then becomes an image set of its own.</small> |
| `--required_metadata` | string<br><small>pattern `^\s*\w+(\s*,\s*\w+)*\s*$`</small> |  | Metadata names that each image set must have, unique, for example Plate,Well,Site.<br><small>Use the names that the Metadata module of your pipeline makes. The workflow stops if a value is missing or empty, or if two image sets have the same values.</small> |

## Masks and CellProfiler

The segmentation masks that the workflow adds, and how CellProfiler runs.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--save_masks` | boolean | `true` | Save a mask (16-bit label image) for each object type of the pipeline. |
| `--mask_objects` | string |  | Save masks only for these objects, separated by commas, for example Nuclei,Cells. Empty = all objects. |
| `--mask_format` | string<br><small>one of `tiff`, `png`, `npy`</small> | `tiff` | The file format of the masks. tiff and png are 16-bit images. npy holds the raw label numbers. |
| `--allow_unpatched` | boolean | `false` | If the preparation of the pipeline fails, run the original pipeline. Masks and tables are then not certain. |
| `--container` | string | `cellprofiler/cellprofiler@sha256:fec440caa2b44edf80f9bd440a3d8c6b214d72437332ad2586a32d79e2eae2a4` | The CellProfiler container image. Use the CellProfiler version of your pipeline.<br><small>The default is pinned by its digest, so each run uses the same image.</small> |
| `--plugins_dir` | string<br><small>directory-path</small> |  | A folder with CellProfiler plugins. |
| `--cellprofiler_args` | string | `""` | More options for the cellprofiler command, for example '--conserve-memory True'. |

## Computer resources

The maximum resources of one job. A new try after a memory or time error asks for more, up to these limits.

| Parameter | Type | Default | Description |
|---|---|---|---|
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

