# Run cp-headless on Berzelius

Berzelius is a cluster at the National Supercomputer Centre (NSC) in Linköping, Sweden. NAISS gives access
to it. Most of its nodes have GPUs, but CellProfiler uses only CPUs. Thus this workflow sends all its jobs to
the **CPU nodes** of Berzelius. It never uses a GPU node, because your project then pays for GPUs that do
nothing.

This guide tells you how to run the workflow on Berzelius, step by step. Read the
[home page](../index.md) and the [tutorial](../tutorials/first-run.md) first.

!!! note "Testing status"
    The tests of the workflow check the Berzelius job scripts with fake `sbatch` and `apptainer` programs.
    We ran `smoke_test.sh` with Docker in place of Apptainer. Nobody has run the workflow on Berzelius itself
    yet. Run step 5 (the smoke test) before your first real run.

> **Do not put sensitive data on Berzelius.** Berzelius does not allow sensitive personal data, for example
> data that the GDPR protects. Ask NAISS support for a different system for such data.

## Contents

- [What the `berzelius` profile does](#what-the-berzelius-profile-does)
- [What you need](#what-you-need)
- [Step 1. Get the code](#step-1-get-the-code)
- [Step 2. Check your project](#step-2-check-your-project)
- [Step 3. Install Nextflow](#step-3-install-nextflow)
- [Step 4. Make your settings file](#step-4-make-your-settings-file)
- [Step 5. Run the test on a compute node](#step-5-run-the-test-on-a-compute-node)
- [Step 6. Write the parameters of your run](#step-6-write-the-parameters-of-your-run)
- [Step 7. Start the run](#step-7-start-the-run)
- [Step 8. After the run](#step-8-after-the-run)
- [Choose the chunk size](#choose-the-chunk-size)
- [Cost](#cost)
- [Storage and file counts](#storage-and-file-counts)
- [Troubleshooting](#troubleshooting)
- [Sources](#sources)

## What the `berzelius` profile does

The profile is in `conf/berzelius.config`. It follows the rules of Berzelius:

| Berzelius rule | What the workflow does |
| --- | --- |
| CPU work must go to a CPU partition: `berzelius-cpu` (Ampere system) or `berzelius-hopper-cpu` (Hopper system). | Each job goes to the CPU partition that you choose. The workflow stops before it submits a job if the partition is not a CPU partition. |
| Each job needs a project account. | The workflow stops if you give no account. |
| A CPU node has 128 cores and about 7.7 GB of memory per core. Slurm charges each core. | A CellProfiler job asks for 1 core and 7 GB. Each new try after a memory error adds 1 core and 7 GB. |
| A job can run for 72 hours or less. | No job asks for more than 72 hours. |
| Each job has a fast local disk at `/scratch/local`. Slurm removes its files when the job ends. | Each job runs on `/scratch/local`. The workflow copies the results back to `/proj` before the job ends. |
| Berzelius has Apptainer. It does not have Docker. | CellProfiler runs in Apptainer. The workflow keeps the image in `/proj`. |
| There are only 8 CPU nodes per system, and all projects share them. | The workflow keeps 64 jobs or fewer in the queue and submits 10 jobs per minute or fewer. |
| `/home` has 20 GB and 1 million files. | The workflow stops if the work folder, the results or the image cache is in your home folder. |
| Packages in your home folder can change Python programs in a container. | CellProfiler ignores your own Python packages (`PYTHONNOUSERSITE=1`). |

The helper scripts are in `scripts/berzelius/`:

| Script | Use |
| --- | --- |
| `preflight.sh` | Shows your projects, quotas, partitions and software. It changes nothing. |
| `berzelius.env.example` | A template for your settings file. |
| `smoke_test.sh` | Runs the test data on one compute node. Use it before your first real run. |
| `submit.sh` | Checks your settings and starts the run. |
| `run_nextflow.sbatch` | The Slurm job that runs Nextflow. `submit.sh` submits it for you. |

## What you need

Collect these facts before you start. Do not guess them.

| Fact | How to find it |
| --- | --- |
| Your project account | Run `projinfo` on a login node. |
| Your system: Ampere or Hopper | Your project allocation decides it. Log in to `berzelius.nsc.liu.se` for Ampere or to `berzelius-hopper.nsc.liu.se` for Hopper. |
| Your project folder | Usually `/proj/<project>/users/$USER`. In this guide, `$PROJ` means this folder. |
| Your images | Copy them into `/proj`, for example with `rsync -av --partial`. First look in `/proj/common-datasets`. |
| Your CellProfiler pipeline | A `.cppipe` file from CellProfiler 4.2.8. |

## Step 1. Get the code

Log in to a login node and put the code into your project folder, not into your home folder:

```bash
ssh <user>@berzelius.nsc.liu.se        # or berzelius-hopper.nsc.liu.se
PROJ=/proj/<project>/users/$USER
git clone <repository-url> "$PROJ/cp-headless"
cd "$PROJ/cp-headless"
```

Use login nodes only to edit files, to copy small files and to submit jobs. Do not run CellProfiler on a
login node.

## Step 2. Check your project

```bash
bash scripts/berzelius/preflight.sh <project-account> "$PROJ"
```

The script shows your projects and quotas, the CPU partitions and their nodes, and the software that it
finds. It warns if Nextflow or Apptainer files are in your home folder.

## Step 3. Install Nextflow

Nextflow needs Java 17 to 26. First, look for a module with `module avail nextflow`. If there is no module,
make a conda environment in `/proj`. Do this in an interactive job on a CPU node:

```bash
interactive -A <project-account> -p berzelius-cpu -n 1 -c 4 -t 01:00:00
module load Miniforge3/<version>                 # see: module avail Miniforge3
mamba create -p "$PROJ/envs/nextflow" -c conda-forge -c bioconda nextflow=26.04.6 openjdk=21
exit
```

Write down the exact versions. The settings file in the next step loads them for each run.

## Step 4. Make your settings file

```bash
cp scripts/berzelius/berzelius.env.example "$PROJ/cp-headless.env"
nano "$PROJ/cp-headless.env"
```

Replace each `<...>` in the file. The file does these things:

- It loads Nextflow and Java (as a module or from your conda environment).
- It sets `NXF_HOME`, `NXF_APPTAINER_CACHEDIR` and `APPTAINER_CACHEDIR` to folders in `/proj`.

## Step 5. Run the test on a compute node

The test downloads the CellProfiler image into your image cache. Then it runs CellProfiler on the 6 test
images. It shows you that Nextflow, Apptainer and CellProfiler work on Berzelius.

```bash
interactive -A <project-account> -p berzelius-cpu -n 1 -c 4 -t 01:00:00
cd "$PROJ/cp-headless"
bash scripts/berzelius/smoke_test.sh "$PROJ/cp-headless.env" "$PROJ/cp-smoke"
exit
```

The last lines must be:

```text
Result: 6 image sets and 51 nuclei. Expected: 6 image sets and 51 nuclei.
OK: CellProfiler works on Berzelius.
```

If you get different numbers, do not start a large run. Find the cause first.

## Step 6. Write the parameters of your run

Write a params file, for example `$PROJ/runs/plate1.yml`. Put all paths in `/proj`:

```yaml
pipeline: /proj/<project>/users/<user>/pipelines/analysis.cppipe
input_dir: /proj/<project>/users/<user>/images/plate1
outdir: /proj/<project>/users/<user>/results/plate1
group_regex: '^(.+?_s\d+)_w\d'
chunk_size: 150
required_metadata: Plate,Well,Site
```

See [Run on your data](../usage.md) for [`group_regex`](../usage.md#group-the-files-of-one-site) and
[`required_metadata`](../usage.md#metadata-for-profiling). See [Choose the chunk size](#choose-the-chunk-size)
for `chunk_size`.

## Step 7. Start the run

Start the run from a login node with `submit.sh`:

```bash
bash scripts/berzelius/submit.sh \
    -A <project-account> \
    -s ampere \
    -e "$PROJ/cp-headless.env" \
    -p "$PROJ/runs/plate1.yml" \
    -r "$PROJ/runs/plate1"
```

| Option | Meaning |
| --- | --- |
| `-A` | Your project account |
| `-s` | `ampere` (partition `berzelius-cpu`) or `hopper` (partition `berzelius-hopper-cpu`) |
| `-e` | Your settings file from step 4 |
| `-p` | Your params file from step 6 |
| `-r` | The run folder in `/proj`. It holds the work files, the logs and the cache for `-resume`. |
| `-n` | Check only: show the `sbatch` command, but do not submit it |
| `-- ...` | More options for `nextflow run`, for example `-- --chunk_size 100` |

`submit.sh` first checks your settings. Then it submits one Slurm job, the **head job**. The head job runs
Nextflow on a CPU node with 2 cores for 72 hours or less. Nextflow submits the CellProfiler jobs. These jobs
use the same account and partition as the head job.

Follow the run:

```bash
squeue -u "$USER"                             # your jobs in the queue
tail -f "$PROJ/runs/plate1/logs/head-<jobid>.out"   # the log of the head job
```

**Continue a stopped run.** A head job stops after 72 hours. It also stops after an error. Run the same
`submit.sh` command again with the same run folder. Nextflow then continues with `-resume`. It does not run
the completed jobs again. `submit.sh` refuses to start a second head job in a run folder that has a running
head job.

## Step 8. After the run

1. Read the results in your `outdir`. Start with these files:
   - `pipeline/patch_report.json`: the changes that the workflow made to your pipeline.
   - `logs/qc_<chunk>.json`: the checks of each chunk and the number of images without objects.
   - `features/merge_report.json`: the number of rows of each merged table.
2. Read the resources that the jobs used in `$PROJ/runs/plate1/pipeline_info/trace_<jobid>.txt`. The column
   `peak_rss` shows the memory and `realtime` shows the time of each job.
3. Remove the work files when you no longer need `-resume`. The work folder holds many small files, and
   `/proj` allows only 2 million files. Remove the files only when the results are in `outdir` as copies
   (`publish_mode: copy`, the default):

   ```bash
   cd "$PROJ/runs/plate1"
   nextflow clean -f        # removes the work files of the last run in this folder
   nscquota                 # shows your space and file counts
   ```

## Choose the chunk size

A good job takes 15 to 60 minutes. Very short jobs load the scheduler. Very long jobs lose more work when
they fail.

1. Run one plate, or part of it, with a small chunk size, for example `chunk_size: 20`.
2. In `trace_<jobid>.txt`, find the time of the CellProfiler jobs. Divide it by the chunk size. The result
   is the time for one image set.
3. Calculate the chunk size: `chunk_size = 1800 s / time for one image set`. That gives jobs of about
   30 minutes.

Example: one image set takes 12 seconds. Then `chunk_size = 1800 / 12 = 150`.

With `chunk_size: 0`, all image sets run in one job. Such a job must also finish in 72 hours. For more than
500 image sets, the workflow shows a warning.

If jobs fail because of memory, the workflow tries again with 1 more core and 7 GB more memory. If many jobs
need a second try, the images need more memory. Look at `peak_rss` in the trace file.

## Cost

Slurm charges your project 1 unit for each core and hour. On the Ampere system, 16 cores cost the same as
1 A100 GPU. The CPU work of CellProfiler is thus cheap. The small number of CPU nodes is the real limit.

Example (an estimate, not a measurement): a plate with 384 wells and 9 sites has 3,456 image sets. At
12 seconds per image set, CellProfiler needs about 11.5 core-hours. That is about 0.7 GPU-hours on Ampere.
The head job adds 2 cores for the duration of the run. For a run of 10 hours, that is 20 core-hours
(about 1.3 GPU-hours).

The workflow keeps 64 jobs or fewer in the queue (`executor.queueSize`). All projects share the CPU nodes.
Speak with the other users of your project before you increase this number.

## Storage and file counts

| Place | Limit | Use it for |
| --- | --- | --- |
| `/home/$USER` | 20 GB, 1 million files | Small configuration files only |
| `/proj/<project>` | 2,000 GiB, 2 million files (more on request in SUPR) | Images, code, results, work folders, the image cache |
| `/scratch/local` | 6.4 TB on each CPU node | Only during a job. Slurm removes its files when the job ends. |

The number of files is usually the first limit. Each job leaves about 10 files in the work folder, plus
its outputs. 5,000 jobs thus give about 50,000 files. Remove the work files after each run (step 8).
`nscquota` shows your use.

There is no backup of `/proj`. Keep a copy of your raw images in a different place.

## Troubleshooting

| Problem | Cause and solution |
| --- | --- |
| `-profile berzelius needs --slurm_account` | Give your account with `-A` to `submit.sh`. `projinfo` shows it. |
| `-profile berzelius needs --slurm_partition berzelius-cpu ...` | Use `-s ampere` or `-s hopper` with `submit.sh`. |
| `... is in your home directory` | Put the run folder, the results and the image cache in `/proj`. |
| Jobs wait with reason `Resources` or `Priority` | The CPU nodes are busy. Wait, or use a larger chunk size, which gives fewer jobs. |
| Jobs wait with reason `AssocGrpGRESRunMinutes` | Your project used its allocation for this month. `projinfo` shows it. |
| `Disk quota exceeded` | Run `nscquota`. Usually there are too many files. Remove old work folders. |
| A job cannot download the image | Run step 5 again. It puts the image into the cache before the run. |
| The head job stopped after 72 hours | Run the same `submit.sh` command again. The run continues. |
| CellProfiler is slower than expected | Check that your pipeline uses no GPU plugin, for example Cellpose. On CPU nodes, such plugins are very slow. |

To ask for help, write to berzelius-support@nsc.liu.se. Write one message for each problem. Give the job ID,
the script, the full error message and the versions of your modules. The system status is at
https://www.nsc.liu.se/systemstatus/.

## Sources

We checked these facts on 2026-10-14 in the
[Berzelius documentation](https://hpc.pages.naiss.se/user-documentation/berzelius-docs/):

- the names of the CPU partitions and the 72-hour limit,
- the hardware of the CPU nodes and the charge per core,
- the storage quotas and the use of Apptainer.
 Partitions and limits can change. Read the documentation again before a large run.
