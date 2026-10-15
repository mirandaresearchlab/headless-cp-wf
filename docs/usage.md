# Run on your data

This page tells you how to prepare your images and your pipeline, and how to start a run.
Do the [tutorial](tutorials/first-run.md) first.

## Prepare the input

You need two things.

**1. A CellProfiler pipeline** (`.cppipe` or `.cpproj`), made in CellProfiler **4.2.8**. The line
`DateRevision: 428` at the top of a `.cppipe` file means 4.2.8. The pipeline must find its images with the
Images, Metadata and NamesAndTypes modules. The workflow gives CellProfiler a list of files for each job.
See [CellProfiler pipelines](reference/pipelines.md) for the other requirements.

**2. An image folder.** The workflow searches it and all its sub-folders for files with an image extension
(`--extensions`). It skips hidden files. For example:

```text
images/
├── plate1/
│   ├── A01_s1_w1.tif   A01_s1_w2.tif      site 1 of well A01, channels 1 and 2
│   ├── A01_s2_w1.tif   A01_s2_w2.tif
│   └── ...
└── plate2/
    └── ...
```

For more layouts (one folder for each channel, one folder for each well), see
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
| One channel: each file is one image set | `'^(.+)$'` |
| `A01_s1_w1.tif`, `A01_s1_w2.tif` (MetaXpress) | `'^(.+?_s\d+)_w\d'` |
| `r01c01f01p01-ch1sk1fk1fl1.tiff` (Opera, Operetta) | `'(r\d+c\d+f\d+p\d+)-ch'` |
| `plate1/B03/site2_DAPI.tif` | `'^(.+/site\d+)_'` |

The workflow then checks the image sets before CellProfiler starts. Every file must match the pattern, and
every image set must have the same number of files. If a check fails, the run stops and shows examples. See
[Data checks and design](explanation/design.md).

To test your pattern before a large run, run the workflow with `-stub-run`. It makes the checks and starts no
CellProfiler job. See [Check the folder before a large run](how-to/format-image-folder.md#check-the-folder-before-a-large-run).

## Choose the chunk size

`--chunk_size` is the number of image sets in one CellProfiler job. The jobs run at the same time.

- `0` (the default) puts all image sets into one job. This is always correct, but slow for large data.
- On a cluster, choose a size that gives jobs of 15 to 60 minutes. See
  [Choose the chunk size](how-to/run-on-berzelius.md#choose-the-chunk-size).

Some pipelines must process all images in one job, for example illumination correction calculated from all
images. The workflow stops if you divide such a pipeline into chunks. Use `--chunk_size 0` for them.

## Start the run

```bash
nextflow run . -profile docker \
    --pipeline    /path/to/analysis.cppipe \
    --input_dir   /path/to/images \
    --outdir      /path/to/results \
    --group_regex '^(.+?_s\d+)_w\d' \
    --chunk_size  50 \
    --max_cpus 8 --max_memory '32.GB'
```

Set `--max_cpus` and `--max_memory` to the size of your computer. Each CellProfiler job asks for 1 core and
8 GB.

You can also keep the parameters in a file and give it with `-params-file`. This keeps a record of the run:

```yaml title="params.yml"
pipeline: /data/exp1/analysis.cppipe
input_dir: /data/exp1/images
outdir: /data/exp1/results
group_regex: '^(.+?_s\d+)_w\d'
chunk_size: 50
required_metadata: Plate,Well,Site
max_memory: 32.GB
```

```bash
nextflow run . -profile docker -params-file params.yml
```

All parameters are in the [parameter reference](reference/parameters.md).

## Profiles

Choose one or more profiles with `-profile`, separated by commas.

| Profile | Use when |
| --- | --- |
| `test` | You want to run the included test data |
| `docker` | You run on a laptop or workstation with Docker |
| `apptainer`, `singularity` | You run on a computer with Apptainer or Singularity |
| `local` | You installed CellProfiler on your computer (no container) |
| `slurm` | You run on a Slurm cluster. See [Run on a Slurm cluster](how-to/run-on-hpc.md). |
| `berzelius` | You run on Berzelius. See [Run on Berzelius](how-to/run-on-berzelius.md). |

## Continue a run

Add `-resume` to continue a run that stopped. Nextflow runs only the jobs that changed or failed, and uses
the results of the other jobs. Start the run from the same folder, because Nextflow keeps its cache in
`.nextflow/` there.

## Metadata for profiling

For profiling, you join the tables on plate, well and site. Your pipeline gets these values from the file
names or folder names with its Metadata module. Add `--required_metadata Plate,Well,Site` (use the names that
your Metadata module makes). The workflow then stops if a value is missing or empty, or if two image sets
have the same values.

## Next steps

- What each result file contains: [Output](output.md).
- Problems: [Troubleshooting](how-to/troubleshooting.md).
