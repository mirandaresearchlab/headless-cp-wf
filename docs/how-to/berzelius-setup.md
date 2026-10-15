# Berzelius: set up

Berzelius is a cluster at the National Supercomputer Centre (NSC) in Linköping, Sweden. NAISS gives access
to it. Most of its nodes have GPUs, but CellProfiler uses only CPUs. Thus this workflow sends all its jobs to
the **CPU nodes** of Berzelius. It never uses a GPU node, because your project then pays for GPUs that do
nothing.

This page prepares Berzelius for the workflow, once. Then you run the workflow in one of two ways:

| Way | How it works | Use it for | Guide |
| --- | --- | --- | --- |
| Interactive | You start an interactive job on one CPU node. All CellProfiler jobs run on that node. | Tests, and small runs that end within the time of the job | [Berzelius: interactive run](berzelius-interactive.md) |
| Batch (Slurm) | A small Slurm job (the head job) runs Nextflow. Nextflow submits one Slurm job for each chunk. | Large runs, many hours, many nodes | [Berzelius: batch run](berzelius-batch.md) |

Do not mix the two ways. In an interactive job, Nextflow must not submit Slurm jobs. The interactive script
makes sure of that.

!!! note "Testing status"
    On 2026-10-15, `smoke_test.sh` (step 5) ran on a CPU node of the Ampere system (`berzelius-cpu`). It
    gave the expected result: 6 image sets and 51 nuclei. The tests of the workflow also check the scripts
    with fake `sbatch` and `apptainer` programs. Run step 5 before your first real run.

> **Do not put sensitive data on Berzelius.** Berzelius does not allow sensitive personal data, for example
> data that the GDPR protects. Ask NAISS support for a different system for such data.

## Contents

- [What the `berzelius` profile does](#what-the-berzelius-profile-does)
- [What you need](#what-you-need)
- [Find your project account](#find-your-project-account)
- [Step 1. Get the code](#step-1-get-the-code)
- [Step 2. Check your project](#step-2-check-your-project)
- [Step 3. Install Nextflow](#step-3-install-nextflow)
- [Step 4. Make your settings file](#step-4-make-your-settings-file)
- [Step 5. Run the test on a compute node](#step-5-run-the-test-on-a-compute-node)
- [Step 6. Write the parameters of your run](#step-6-write-the-parameters-of-your-run)
- [After a run](#after-a-run)
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
| `make_env.sh` | Writes your settings file from options. You do not edit a file. |
| `smoke_test.sh` | Runs the test data on one compute node. Use it before your first real run. |
| `run_interactive.sh` | Runs your data inside an interactive job, on one node. |
| `submit.sh` | Checks your settings and starts a batch run. |
| `run_nextflow.sbatch` | The Slurm job that runs Nextflow. `submit.sh` submits it for you. |

## What you need

Collect these facts before you start. Do not guess them.

| Fact | How to find it |
| --- | --- |
| Your project account | The Slurm account of your project, for example `berzelius-2026-177`. See [Find your project account](#find-your-project-account). |
| Your system: Ampere or Hopper | Your project allocation decides it. Log in to `berzelius.nsc.liu.se` for Ampere or to `berzelius-hopper.nsc.liu.se` for Hopper. |
| Your project folder | Usually `/proj/<project>/users/$USER`. In this guide, `$PROJ` means this folder. The name of this folder can differ from the name of the account. |
| Your images | Copy them into `/proj`, for example with `rsync -av --partial`. First look in `/proj/common-datasets`. |
| Your CellProfiler pipeline | A `.cppipe` file from CellProfiler 4.2.8. |

## Find your project account

Slurm needs the **project account** for each job (`-A <project-account>`). It is the name of your project in
Slurm. It is **not** your user name (the one that starts with `x_`). It can also differ from the name of
your storage folder in `/proj`. For example, the folder `/proj/berzelius-2025-380` can belong to the account
`berzelius-2026-177`.

On a login node, run:

```bash
projinfo
```

```text
You are a member of 1 active project.

Berzelius-2026-177
══════════════════
Principal Investigator (PI):   <name of the PI>
Project storage directory:     /proj/berzelius-2025-380
Slurm account:                 berzelius-2026-177
```

Use the line `Slurm account` for `-A`. Use the line `Project storage directory` for `$PROJ`. In this
example, the two names differ.

Test the account before you use it. An interactive job on a CPU node must start:

```bash
interactive -A <project-account> -p berzelius-cpu -n 1 -c 4 -t 00:05:00
```

**If you cannot find your account:**

1. Run `sacctmgr show assoc user=$USER format=account%30,partition%20`. The column `Account` lists the
   accounts that you can use.
2. Compare it with the message that you get. `Invalid account or account/partition combination specified`
   means that the account name is wrong, or that your user does not belong to the project.
3. `projinfo` can say that you are a member of no project, or show an empty list. Then ask the PI of your
   project to add you to the project in [SUPR](https://supr.naiss.se). Then log in again and run `projinfo`.
4. If it still does not work, write to berzelius-support@nsc.liu.se. Give your user name, the account name
   that you tried and the full error message.

## Step 1. Get the code

Log in to a login node and put the code into your project folder, not into your home folder:

```bash
ssh <user>@berzelius.nsc.liu.se        # or berzelius-hopper.nsc.liu.se
export PROJ=/proj/<project>/users/$USER
git clone https://github.com/mirandaresearchlab/headless-cp-wf.git "$PROJ/cp-headless"
cd "$PROJ/cp-headless"
```

Use login nodes only to edit files, to copy small files and to submit jobs. Do not run CellProfiler on a
login node.

!!! warning "Run the Berzelius commands on Berzelius"
    Check the prompt before you run a command. On Berzelius it looks like `[x_user@berzelius1 ...]$`. If
    you see the name of your own computer, you are not on Berzelius. On a Mac, the command
    `mkdir /proj/...` then fails with `Read-only file system`.

## Step 2. Check your project

```bash
bash scripts/berzelius/preflight.sh <project-account> "$PROJ"
```

The script shows your projects and quotas, the CPU partitions and their nodes, and the software that it
finds. It warns if Nextflow or Apptainer files are in your home folder.

## Step 3. Install Nextflow

Nextflow needs Java 17 to 26. First, look for a module with `module avail nextflow`. If there is no module,
make a conda environment in `/proj`. Do this in an interactive job on a CPU node:

1. Start the job:

   ```bash
   interactive -A <project-account> -p berzelius-cpu -n 1 -c 4 -t 01:00:00
   ```

2. **Set `PROJ` again on the node, with `export`.** A job starts a new shell. It does not keep a variable that
   you set without `export` on the login node. If `PROJ` is empty, the path `"$PROJ/envs/nextflow"` becomes
   `/envs/nextflow`, and `mamba` stops with `Permission denied`.

   ```bash
   export PROJ=/proj/<project>/users/$USER
   echo "$PROJ"          # it must show your folder, not an empty line
   ```

3. Load Miniforge and make the environment:

   ```bash
   module load Miniforge3
   mamba create -p "$PROJ/envs/nextflow" -c conda-forge -c bioconda nextflow=26.04.6 openjdk=21
   ```

   `module load Miniforge3` loads the default version. You do not need to name a version. To use one
   exact version, name it, for example `module load Miniforge3/25.3.1-0`. `module avail Miniforge3` lists the
   versions. It marks the default with `(D)`.

4. Check the result, then leave the job:

   ```bash
   "$PROJ/envs/nextflow/bin/nextflow" -version
   exit
   ```

If `mamba` stops with an error about a lock, see [`mamba` stops because of a lock](#mamba-stops-because-of-a-lock).

!!! tip "The `mamba` message about security"
    `mamba` asks `Confirm changes: [Y/n]` and shows a warning about package scripts. This is normal for the
    conda-forge and bioconda channels. Type `y`.

## Step 4. Make your settings file

The script `make_env.sh` writes the settings file from your options. You do not copy or edit a file.

```bash
bash scripts/berzelius/make_env.sh -p "$PROJ"
```

| Option | Meaning |
| --- | --- |
| `-p` | Your project folder in `/proj` (required) |
| `-m` | The Miniforge module. The default is `Miniforge3` (the default version). To pin a version: `-m Miniforge3/25.3.1-0` |
| `-c` | The conda environment with Nextflow. The default is `$PROJ/envs/nextflow`. |
| `-o` | The file to write. The default is `$PROJ/cp-headless.env`. |
| `-f` | Replace the file if it exists |

The script stops, and writes nothing, if the path has a `<placeholder>`, is in your home folder, or if the
file exists (use `-f`). The file that it writes does these things:

- It loads Miniforge and your conda environment, so that `nextflow` and Java work.
- It exports `PROJ`, `NXF_HOME`, `NXF_APPTAINER_CACHEDIR` and `APPTAINER_CACHEDIR`. All of them point to
  folders in `/proj`.

To change a value, run the script again with `-f`.

## Step 5. Run the test on a compute node

The test downloads the CellProfiler image into your image cache. Then it runs CellProfiler on the 6 test
images. It shows you that Nextflow, Apptainer and CellProfiler work on Berzelius.

```bash
interactive -A <project-account> -p berzelius-cpu -n 1 -c 4 -t 01:00:00
export PROJ=/proj/<project>/users/$USER      # again: a job starts a new shell
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

A YAML file does not expand `$USER`. Write your own user name for `<user>`. `echo $USER` shows it.

See [Run on your data](../usage.md) for [`group_regex`](../usage.md#group-the-files-of-one-site) and
[`required_metadata`](../usage.md#metadata-for-profiling). See [Choose the chunk size](berzelius-batch.md#choose-the-chunk-size)
for `chunk_size`.

Then start the run: [interactive](berzelius-interactive.md) or [batch](berzelius-batch.md).

## After a run

1. Read the results in your `outdir`. Start with these files:
   - `pipeline/patch_report.json`: the changes that the workflow made to your pipeline.
   - `logs/qc_<chunk>.json`: the checks of each chunk and the number of images without objects.
   - `features/merge_report.json`: the number of rows of each merged table.
2. Read the resources that the jobs used in the trace file. A batch run writes
   `$PROJ/runs/plate1/pipeline_info/trace_<jobid>.txt`. An interactive run writes `pipeline_info/trace.txt`
   in your `outdir`. The column `peak_rss` shows the memory and `realtime` shows the time of each job.
3. Remove the work files when you no longer need `-resume`. The work folder holds many small files, and
   `/proj` allows only 2 million files. Remove the files only when the results are in `outdir` as copies
   (`publish_mode: copy`, the default):

   ```bash
   cd "$PROJ/runs/plate1"
   nextflow clean -f        # removes the work files of the last run in this folder
   nscquota                 # shows your space and file counts
   ```

## Storage and file counts

| Place | Limit | Use it for |
| --- | --- | --- |
| `/home/$USER` | 20 GB, 1 million files | Small configuration files only |
| `/proj/<project>` | 2,000 GiB, 2 million files (more on request in SUPR) | Images, code, results, work folders, the image cache |
| `/scratch/local` | 6.4 TB on each CPU node | Only during a job. Slurm removes its files when the job ends. |

The number of files is usually the first limit. Each job leaves about 10 files in the work folder, plus
its outputs. 5,000 jobs thus give about 50,000 files. Remove the work files after each run ([After a run](#after-a-run)).
`nscquota` shows your use.

There is no backup of `/proj`. Keep a copy of your raw images in a different place.

## Troubleshooting

| Problem | Cause and solution |
| --- | --- |
| `-profile berzelius needs --slurm_account` | Give your account with `-A` to `submit.sh` or to `interactive`. `projinfo` shows it. |
| `-profile berzelius needs --slurm_partition berzelius-cpu ...` | Use `-s ampere` or `-s hopper` with `submit.sh`. |
| `... is in your home directory` | Put the run folder, the results and the image cache in `/proj`. |
| Jobs wait with reason `Resources` or `Priority` | The CPU nodes are busy. Wait, or use a larger chunk size, which gives fewer jobs. |
| Jobs wait with reason `AssocGrpGRESRunMinutes` | Your project used its allocation for this month. `projinfo` shows it. |
| `Disk quota exceeded` | Run `nscquota`. Usually there are too many files. Remove old work folders. |
| `Invalid account or account/partition combination specified` | The account name is wrong. Your user name (`x_...`) is not an account. See [Find your project account](#find-your-project-account). |
| `mamba` stops with `Permission denied [/envs/nextflow/...]` | `PROJ` is empty in this shell, so the path starts at `/`. Run `export PROJ=/proj/<project>/users/$USER`, check it with `echo "$PROJ"`, and run `mamba create` again (step 3). |
| `mamba` stops with `Read-only file system ["/proj"]` | You run the command on your own computer. Run it on Berzelius. |
| `mamba` stops because of a lock | See [`mamba` stops because of a lock](#mamba-stops-because-of-a-lock). |
| `Docker references with both a tag and digest are currently not supported` | Apptainer cannot pull `image:tag@sha256:...`. Use `--container 'cellprofiler/cellprofiler@sha256:<digest>'` (no tag). The default of the workflow already has this form. Update the code with `git pull`. |
| A job cannot download the image | Run step 5 again. It puts the image into the cache before the run. |
| The head job stopped after 72 hours | Run the same `submit.sh` command again. The run continues. |
| `run this inside an interactive job on a CPU node` | Start an interactive job first. See [Berzelius: interactive run](berzelius-interactive.md). |
| CellProfiler is slower than expected | Check that your pipeline uses no GPU plugin, for example Cellpose. On CPU nodes, such plugins are very slow. |

### `mamba` stops because of a lock

A lock error means that another `mamba` or `conda` process holds a lock file, or that an earlier run stopped
and left one. The quickest way to solve it:

1. Check that no other `mamba` of yours is running (for example in a second terminal):

   ```bash
   pgrep -u "$USER" -a mamba
   ```

   If it lists a running process, wait until it ends. A line that ends with `<defunct>` in `ps` is a finished
   process that the system has not cleaned up yet. It holds no lock. Ignore it.

2. Remove the lock files. Look first, then remove them:

   ```bash
   find ~/.mamba ~/.conda "$PROJ/envs" -name "*.lock" 2>/dev/null
   find ~/.mamba ~/.conda "$PROJ/envs" -name "*.lock" -delete 2>/dev/null
   ```

3. If the first run stopped in the middle, remove the half-made environment. Then run `mamba create` again:

   ```bash
   rm -rf "$PROJ/envs/nextflow"
   ```

   Check that `echo "$PROJ"` shows your folder before you run `rm -rf`. An empty `PROJ` points `rm` to `/envs`.

If the error stays, write the full message to berzelius-support@nsc.liu.se. We have not tested these steps
on Berzelius.

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
