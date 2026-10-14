# cp-headless

cp-headless measures cells in large sets of microscope images. It runs **CellProfiler** without its
graphical window ("headless"). It uses **Nextflow** to run many CellProfiler jobs at the same time, on a
laptop or on a computer cluster.

You give the workflow two things:

1. a **CellProfiler pipeline** (a `.cppipe` or `.cpproj` file) that you made in the CellProfiler program,
2. a **folder of images**.

The workflow gives you:

- **feature tables**: one row per image and one row per cell (or other object), with measurements such as
  size, shape and intensity,
- **segmentation masks**: one image file per object type (for example nuclei or cells) that shows where each
  object is,
- **reports** that show what the workflow did, which checks it made, and which software versions it used.

These tables are the input for **image-based profiling**. In image-based profiling, you compare the
measurements of cells between treatments, for example drugs or gene changes. Wrong or missing data in
the tables gives wrong biology. Thus the workflow checks the data at each step and stops when something is
wrong. It does not continue with an error that nobody sees.

## Contents

- [Key terms](#key-terms)
- [How the workflow works](#how-the-workflow-works)
- [Checks that protect your data](#checks-that-protect-your-data)
- [Quick start](#quick-start)
- [What you get](#what-you-get)
- [Group the files of one site: `group_regex`](#group-the-files-of-one-site-group_regex)
- [Split the work into chunks: `chunk_size`](#split-the-work-into-chunks-chunk_size)
- [Metadata for profiling](#metadata-for-profiling)
- [Parameters](#parameters)
- [Where to run the workflow](#where-to-run-the-workflow)
- [Troubleshooting](#troubleshooting)
- [Limitations](#limitations)
- [More documents](#more-documents)

## Key terms

| Term | Meaning |
| --- | --- |
| Plate | A plastic plate with many small wells (for example 96 or 384). Each well holds cells. |
| Well | One position on a plate, for example `A01`. |
| Site | One field of view in a well. The microscope often takes images of several sites per well. |
| Channel | One color of light, which shows one stain. For example, `DNA` shows the nucleus. |
| Image set | All channel images of one site. CellProfiler analyzes one image set at a time. |
| Object | Something that CellProfiler finds in the images, for example a nucleus or a cell. |
| Feature | One measurement of an object or an image, for example the area of a nucleus. |
| Mask | An image in which the pixels of object 1 have the value 1, of object 2 the value 2, and so on. The value 0 is the background. |
| Metadata | Information about an image, for example its plate, well and site. CellProfiler can read it from file names. |
| Chunk | A group of image sets that one CellProfiler job processes. |
| Container | A package that holds CellProfiler and everything that it needs. The same container gives the same results on each computer. |
| Cluster (HPC) | A group of many computers. A scheduler, for example Slurm, gives jobs to the computers. |

## How the workflow works

```text
 image folder ──► 1. find the images ──► 2. group them into image sets ──► 3. divide them into chunks
                                                                                    │
 .cppipe file ──► 4. prepare the pipeline (once) ────────────────────────────────-─►│
                                                                                    ▼
                                    5. run CellProfiler on each chunk, at the same time, and check each result
                                                                                    │
                                                                                    ▼
                                    6. merge the tables of all chunks into one table per type
```

1. **Find the images.** The workflow searches the image folder and all its sub-folders. It uses the files
   with an image extension (for example `.tif`). It skips hidden files.
2. **Group the images into image sets.** A pattern (`group_regex`) tells the workflow which files belong to
   the same site. See [Group the files of one site](#group-the-files-of-one-site-group_regex).
3. **Divide the image sets into chunks.** Each chunk becomes one CellProfiler job. The jobs run at the same
   time. A chunk always holds complete image sets.
4. **Prepare the pipeline.** The workflow opens your pipeline with CellProfiler itself and makes these changes:
   - It adds mask saving for every object type that the pipeline finds. The workflow never overwrites a mask.
   - It adds a spreadsheet export (`ExportToSpreadsheet`) if the pipeline has none.
   - It removes `CreateBatchFiles`, which stops a run without a window.
   - It sends all outputs to the output folder of the job. Thus the workflow writes nothing into your image folder.

   The workflow records each change in `pipeline/patch_report.json`. It stops if CellProfiler cannot open
   the pipeline, for example because a plugin is missing or the pipeline comes from a newer CellProfiler.
5. **Run CellProfiler on each chunk.** Each job runs `cellprofiler` with the list of its files. Then a check
   script examines the result of the job (see the next section).
6. **Merge the tables.** CellProfiler starts its image numbers at 1 in each chunk. Thus the workflow adds
   two columns to each merged table:
   - `CPNF_Chunk`: the chunk of the row.
   - `CPNF_GlobalImageNumber`: an image number that is unique in the complete run.

   Use `CPNF_GlobalImageNumber` to join the image table, the object tables and the mask list.

## Checks that protect your data

The workflow stops with a clear message when one of these checks fails.

**Before CellProfiler starts:**

- Every image file must match `group_regex`. A thumbnail or an overlay in the image folder fails this check.
- Every image set must have the same number of files. Thus a site with a missing channel stops the run.
- The output folder and the work folder must not be in the image folder. Otherwise a later run reads the
  results as new images.
- Some pipelines must see all images in one job. Examples are illumination correction across all images
  and object tracking. The workflow refuses to divide these pipelines into chunks.

**After each CellProfiler job:**

- CellProfiler must make an image table, and the table must not be empty.
- The number of image sets must be the same as the number that the workflow predicted.
- For each object type, the count in the image table (`Count_<Object>`) must agree with the number of
  rows in the object table.
- Each image set must have one mask file for each object type.
- If you set `--required_metadata`, each image set must have these metadata values, and they must be unique.

**When the workflow merges the chunks:**

- No two chunks may write the same mask file.
- If you set `--required_metadata`, no site may occur in two chunks.

If you must process imperfect data, some checks have an option to continue with a warning. See
[Parameters](#parameters).

## Quick start

You need:

- **Nextflow** 24.04 or newer, and **Java** 17 to 26,
- **Docker** (on a laptop) or **Apptainer** (on a cluster). You can also use CellProfiler that you installed
  yourself.
- disk space for the `work/` folder of Nextflow and for the results.

Two things to check first:

- Nextflow refuses Java 27 and newer. If `nextflow -version` shows `Cannot find Java or it's a wrong
  version`, select Java 21. On macOS with Homebrew: `export JAVA_HOME=/opt/homebrew/opt/openjdk@21`.
- If you installed Nextflow with `./scripts/bootstrap.sh`, it is in `.venv`. Activate it first:
  `source .venv/bin/activate`.

`bash scripts/test-nextflow.sh` runs step 1 below and finds Nextflow and a supported Java itself.

```bash
# 1. Check the workflow structure. This does not run CellProfiler and takes a few seconds.
nextflow run . -profile test,local -stub-run

# 2. Run the included test: 6 small images, real CellProfiler in Docker.
nextflow run . -profile test,docker

# 3. Run your own data.
nextflow run . -profile docker \
    --pipeline    /path/to/analysis.cppipe \
    --input_dir   /path/to/images \
    --outdir      results \
    --group_regex '^(.+?_s\d+)_w\d' \
    --chunk_size  50 \
    --max_cpus 8 --max_memory '32.GB'
```

You can also write the parameters in a file and give it with `-params-file params.yml`:

```yaml
pipeline: /data/exp1/analysis.cppipe
input_dir: /data/exp1/images
outdir: /data/exp1/results
group_regex: '^(.+?_s\d+)_w\d'
chunk_size: 50
required_metadata: Plate,Well,Site
max_memory: 32.GB
```

- Add `-resume` to continue a run. Nextflow then runs only the jobs that changed or failed.
- Use `-c my.config` for your own Nextflow settings.

**CellProfiler version.** The `docker` profile uses CellProfiler 4.2.8. The workflow pins the image by its
digest, so each run uses the same image. Your pipeline must come from the same CellProfiler version. The
line `DateRevision: 428` at the top of a `.cppipe` file means 4.2.8. For another version, set `--container`.

## What you get

```text
results/
├── features/              merged tables: one per type (image, each object, experiment),
│                          mask_manifest.csv and merge_report.json
├── masks/                 one mask per image set and object type, in the same sub-folders as the images
├── cellprofiler_outputs/  other files that your own pipeline saves (for example overlays), per chunk
├── pipeline/              patched.cppipe (the pipeline that ran) and patch_report.json (all changes)
├── logs/                  the CellProfiler log and the check results (qc_<chunk>.json) of each chunk
└── pipeline_info/         run_info.json (code version, container, parameters) and Nextflow reports
```

**Masks.** Each mask is a 16-bit image (`.tiff` by default). The value 0 is the background, and the values
1, 2, 3, ... are the objects. The value of an object is the same as its `ObjectNumber` in the object table.

**Mask list.** `features/mask_manifest.csv` has one row for each image set and object type. It connects each
mask to its input images:

```csv
CPNF_Chunk,CPNF_GlobalImageNumber,ImageNumber,Metadata_Plate,FileName_DNA,PathName_DNA,InputPath_DNA,FileName_Actin,PathName_Actin,InputPath_Actin,MaskObject,MaskPath
chunk_0001,1,1,plate1,site1_DNA.tif,plate1,plate1/site1_DNA.tif,site1_Actin.tif,plate1,plate1/site1_Actin.tif,Nuclei,masks/plate1/site1_DNA_Nuclei_mask.tiff
chunk_0001,1,1,plate1,site1_DNA.tif,plate1,plate1/site1_DNA.tif,site1_Actin.tif,plate1,plate1/site1_Actin.tif,Cells,masks/plate1/site1_DNA_Cells_mask.tiff
```

- `InputPath_<channel>` is the path of the input image in `--input_dir`.
- `MaskPath` is the path of the mask in `--outdir`.
- `MaskObject` is the object type, for example `Nuclei` or `Cells`.
- The `Metadata_*`, `FileName_*` and `PathName_*` columns come from the image table of CellProfiler.
- The list contains no temporary paths of the work folder.

With `--gzip_features true`, the workflow writes all merged tables as `.csv.gz`.

## Group the files of one site: `group_regex`

A microscope usually saves one file per channel. CellProfiler must receive all channel files of a site in
the same job. Otherwise it cannot build the image set. `group_regex` is a regular expression. The workflow
applies it to the path of each file in `--input_dir`. The parts in round brackets (capture groups) make the
name of the image set. Files with the same name belong to the same image set.

| File names | `group_regex` |
| --- | --- |
| One channel: each file is one image set | `'^(.+)$'` |
| `A01_s1_w1.tif`, `A01_s1_w2.tif` (MetaXpress) | `'^(.+?_s\d+)_w\d'` |
| `r01c01f01p01-ch1sk1fk1fl1.tiff` (Opera, Operetta) | `'(r\d+c\d+f\d+p\d+)-ch'` |
| `plate1/B03/site2_DAPI.tif` | `'^(.+/site\d+)_'` |

The workflow then checks the image sets:

- Every file must match the pattern.
- Every image set must have the same number of files (one per channel). The workflow uses the most common
  number as the number of channels.

If a check fails, the run stops and shows examples. The usual causes are a missing channel, extra files
(thumbnails, overlays) in the image folder, or a pattern that is too narrow. To continue anyway, set
`--allow_incomplete_sets true`. Each file that does not match then becomes an image set of its own.

## Split the work into chunks: `chunk_size`

`chunk_size` is the number of image sets in one CellProfiler job. The value `0` puts all image sets into one
job. That is always correct, but slow for large data. On a cluster, choose a chunk size that gives jobs of
15 to 60 minutes.

With `chunk_size` more than 0, each job compares the number of image sets from CellProfiler with the number
that the workflow predicted. A difference stops the run, because the channels of a site were probably split
between two chunks. Set `--strict_image_count false` to get only a warning.

**Some pipelines must process all images in one job.** With `chunk_size` more than 0, the workflow stops if
the pipeline contains one of these modules:

- `CorrectIlluminationCalculate` set to "All: First cycle" or "All: Across cycles". In chunks, each chunk
  calculates its own illumination correction, and the intensities of the chunks do not agree.
- `LoadData`. Each chunk would process the complete CSV file.
- `Groups` with grouping on.
- `TrackObjects`, `MakeProjection`, `CalculateStatistics`, or `Tile` across cycles.

Use `--chunk_size 0` for these pipelines. `pipeline/patch_report.json` lists such modules under
`chunk_unsafe_modules`.

## Metadata for profiling

For profiling, you join the tables on plate, well and site. CellProfiler gets these values from the file
names or folder names with its Metadata module. Set `--required_metadata Plate,Well,Site`. Use the names that
your Metadata module makes. The workflow then stops in these cases:

- The image table has no column for one of the names.
- An image set has an empty value.
- Two image sets have the same values, in one chunk or in two different chunks. This can occur when you
  give the same images twice, or when the microscope imaged a plate two times.

For each chunk, the file `logs/qc_<chunk>.json` gives the number of images with zero objects of each type.
Such images can show an empty well, an image that is not in focus, or a segmentation problem.

## Parameters

Boolean parameters accept only `true` or `false`, on the command line or in a params file. Other values stop
the run.

### Input and output

| Parameter | Default | Meaning |
| --- | --- | --- |
| `pipeline` | (required) | The CellProfiler pipeline: `.cppipe` or `.cpproj` |
| `input_dir` | (required) | The image folder. The workflow also searches its sub-folders. |
| `outdir` | `results` | The output folder. It must not be in `input_dir`. |
| `extensions` | `tif,tiff,png,...` | The file extensions of the images. Upper case and lower case are the same. |
| `publish_mode` | `copy` | How results go to `outdir`: `copy`, `symlink` or `link` |
| `gzip_features` | `false` | Write the merged tables as `.csv.gz` |

### Image sets and chunks

| Parameter | Default | Meaning |
| --- | --- | --- |
| `group_regex` | — | The pattern that finds the files of one image set |
| `chunk_size` | `0` | The number of image sets per job. `0` means one job. |
| `strict_image_count` | `true` | Stop if CellProfiler makes a different number of image sets than predicted |
| `allow_incomplete_sets` | `false` | Continue with a warning when a file does not match `group_regex` or an image set has a missing channel |
| `required_metadata` | — | For example `Plate,Well,Site`. These values must be present and unique for each image set. |

### Masks and CellProfiler

| Parameter | Default | Meaning |
| --- | --- | --- |
| `save_masks` | `true` | Save a mask for each object type |
| `mask_objects` | all | Save masks only for these objects, for example `Nuclei,Cells` |
| `mask_format` | `tiff` | `tiff` or `png` (16-bit), or `npy` (raw numbers) |
| `allow_unpatched` | `false` | If the preparation of the pipeline fails, run the original pipeline. Masks and tables are then not certain. |
| `container` | `cellprofiler/cellprofiler:4.2.8@sha256:...` | The CellProfiler container. Use the version of your pipeline. |
| `plugins_dir` | — | A folder with CellProfiler plugins |
| `cellprofiler_args` | `''` | More options for the `cellprofiler` command |

### Computer resources and clusters

| Parameter | Default | Meaning |
| --- | --- | --- |
| `max_cpus`, `max_memory`, `max_time` | 16, 64.GB, 48.h | The maximum for one job. **Set these to the size of your computer or node.** |
| `slurm_account`, `slurm_partition` | — | The Slurm account and partition |
| `slurm_scratch` | — | A folder on the local disk of the node, for example `'$TMPDIR'` |
| `slurm_cluster_options` | — | More `sbatch` options, for example `'--qos=normal'` |
| `container_cache` | — | A shared folder for Apptainer or Singularity images |

Each CellProfiler job asks for 1 CPU core and 8 GB of memory. If the computer stops a job because it uses
too much memory or time, the workflow tries the job again with more memory and time. It tries up to 3
times. The workflow does not try again after other errors. After such an error, it starts no new jobs, but
it lets the running jobs finish. With `-resume`, it then uses their results.

## Where to run the workflow

| Where | How | Profile |
| --- | --- | --- |
| Laptop or workstation | Nextflow on your computer, CellProfiler in Docker | `-profile docker` |
| Laptop, all in one image | Nextflow and CellProfiler in one Docker image. See [below](#all-in-one-docker-image). | none |
| Your own CellProfiler | CellProfiler installed on your computer, for example with conda | `-profile local` |
| Slurm cluster | Jobs go to Slurm, CellProfiler runs in Apptainer | `-profile slurm,apptainer` |
| Berzelius (NSC) | A profile with the rules of Berzelius | `-profile berzelius`, see [docs/berzelius.md](docs/berzelius.md) |

### Slurm clusters

Put the values for your cluster in a params file or in a file for `-c`:

```groovy
// site.config
params.slurm_account   = 'naiss2026-x-yy'
params.slurm_partition = 'shared'
params.container_cache = '/proj/<project>/containers'
params.max_memory      = '200.GB'
executor.queueSize     = 200          // the maximum number of your jobs in the queue
```

- Run Nextflow itself as a long Slurm job with few resources. Do not run it on the login node.
- Put the work folder (`-work-dir`) on shared project storage, not in your home folder.
- Compute nodes often have no internet. Download the image once into `container_cache`.
- Set `--slurm_scratch '$TMPDIR'` only if the nodes have a local disk. On nodes without a disk, scratch
  uses memory.

### All-in-one Docker image

This image holds Nextflow, Java 21, CellProfiler 4.2.8 and the workflow. Inside the image, the workflow uses
the `local` profile. Thus it needs no access to the Docker service of your computer. The CellProfiler 4.2.8
image exists only for Linux on amd64. On Apple Silicon, Docker Desktop emulates it with the
`--platform linux/amd64` option.

```bash
# Build the image once, in the folder of this repository.
docker build --platform linux/amd64 -t cp-headless:1.0.0 .

# Run it. The current folder becomes the work area /workspace.
docker run --rm --platform linux/amd64 \
    --user "$(id -u):$(id -g)" \
    -v "$PWD:/workspace" \
    cp-headless:1.0.0 \
    --pipeline /workspace/analysis.cppipe \
    --input_dir /workspace/images \
    --outdir /workspace/results \
    --group_regex '^(.+_s\d+)_(?:DNA|Actin)\.tif$' \
    --chunk_size 50 \
    --max_cpus 8 \
    --max_memory 32.GB
```

- The work area keeps `work/`, `.nextflow/` and the results. Thus `-resume` also works with this image.
- For data in another folder, add a read-only mount, for example `-v /path/to/data:/data:ro`. Then use
  paths in `/data`.
- On Windows, remove the `--user` line.
- `docker run --rm cp-headless:1.0.0 --help` shows a short help text.

## Troubleshooting

| Message or problem | Cause and solution |
| --- | --- |
| `image set(s) do not have N file(s)` | A channel is missing, or extra files are in the image folder. See [group_regex](#group-the-files-of-one-site-group_regex). |
| `file(s) do not match --group_regex` | Thumbnails or other files are in the image folder, or the pattern is too narrow. |
| `CellProfiler processed N image sets but the workflow predicted M` | `group_regex` does not group the files as your pipeline (NamesAndTypes) does. |
| `must process all image sets in one CellProfiler run` | The pipeline has a module that needs all images. Use `--chunk_size 0`. |
| `--outdir ... is inside --input_dir` | Choose an output folder outside the image folder. |
| `required by --required_metadata` | The Metadata module of your pipeline does not make this value. Check its regular expression. |
| `counts N objects but ... has M rows` | The export of CellProfiler is not complete. Look at the log of the chunk. |
| `CellProfiler reported errors while loading the pipeline` | A plugin is missing (`--plugins_dir`), or the pipeline comes from a newer CellProfiler (`--container`). |
| `trying to overwrite ... in headless mode` | Your own `SaveImages` gives two image sets the same file name. Turn on "Create subfolders" in that module, or rename the input files. |
| `Per-image table is empty` | The filters in the Images or NamesAndTypes module exclude all files. Compare them with your file names and `--extensions`. |
| `Cannot find Java or it's a wrong version` | Nextflow needs Java 17 to 26. Set `JAVA_HOME` to a supported Java, for example `/opt/homebrew/opt/openjdk@21`. |
| `nextflow: command not found` | Activate the development environment (`source .venv/bin/activate`), or install Nextflow. |
| `Process requirement exceeds available memory` | Set `--max_memory` and `--max_cpus` to the size of your computer. |
| `Permission denied: bin/patch_cppipe.py` | Run `chmod +x bin/*.py`. |
| Docker: `cellprofiler: unrecognized arguments ... bash` | Use the `docker` profile. It removes the entry point of the image. |
| Very slow in containers | Keep the thread settings of the workflow. They limit the threads of each job to its CPU cores. |
| `AttributeError: 'str' object has no attribute ...` in `check_chunk.py` | A helper script uses a Python feature that is newer than 3.8. See [docs/development.md](docs/development.md). |

## Limitations

- The workflow names each mask after the first input image of the image set. Some files (`.nd2`, `.czi`)
  hold many sites in one file. Then several image sets get the same mask name, and the run stops. It does
  not overwrite masks. For such files, save masks with names from metadata in your own pipeline.
- Each job links the complete image folder. This is fast on local disks and on shared cluster storage. On
  cloud storage, each chunk copies the folder.
- We tested the workflow with CellProfiler 4.2.8. CellProfiler 5 changes some modules. If you change the
  version, read `patch_report.json`.
- The CellProfiler 4.2.8 image exists only for Linux on amd64. It uses Ubuntu 18.04 and Python 3.8.

## More documents

- [docs/berzelius.md](docs/berzelius.md): run the workflow on the Berzelius cluster, step by step.
- [docs/development.md](docs/development.md): the code, the tests and the automatic checks.
- [CHANGELOG.md](CHANGELOG.md): changes in the behaviour of the workflow.
