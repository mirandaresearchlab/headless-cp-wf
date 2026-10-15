# Run on a Slurm cluster

This guide tells you how to run the workflow on a Slurm cluster with Apptainer or Singularity. For the
Berzelius cluster, use [Run on Berzelius](run-on-berzelius.md), which follows the rules of that site.

!!! note "Testing status"
    The tests of the workflow check the Slurm job scripts with a fake `sbatch` program. The commands on this
    page were not run on a real cluster by the authors of this page.

**Prerequisites:** an account on the cluster, Nextflow and Java 17 to 26 on the cluster, and Apptainer or
Singularity on the compute nodes.

!!! info "Before you start"
    This guide assumes that you cloned the repository, installed the tools and activated the environment.
    If you did not, do [Installation](../getting-started/installation.md) first. To check, open a terminal in the folder `headless-cp-wf`
    and run `source .venv/bin/activate` and then `nextflow -version`. It must print a version number.

## 1. Collect the facts of your cluster

Read the documentation of your cluster, or ask its support, for these facts:

- your project account and the partition for CPU jobs,
- the maximum number of jobs per user and the maximum run time of a job,
- shared project storage for the images, the work folder and the results (not your home folder),
- whether the compute nodes have internet and a local disk.

## 2. Write a site configuration file

Put the facts in a file for `-c`. The workflow reads these values for each job, so they also work in a
`-c` file:

```groovy title="site.config"
params.slurm_account   = '<account>'
params.slurm_partition = '<cpu partition>'
params.container_cache = '/<shared storage>/containers'
params.max_memory      = '200.GB'
executor.queueSize     = 200          // the maximum number of your jobs in the queue
```

| Parameter | Use |
| --- | --- |
| `slurm_account` | The `--account` of each job. Most clusters need one. |
| `slurm_partition` | The partition. Empty = the default partition of the cluster. |
| `slurm_scratch` | A folder on the local disk of the node, for example `'$TMPDIR'`. Set it only if the nodes have a local disk. On nodes without a disk, scratch uses memory. |
| `slurm_cluster_options` | More `sbatch` options, for example `'--qos=normal'`. |
| `container_cache` | A shared folder for the container image. |

The profile is in [`conf/slurm.config`](https://github.com/mirandaresearchlab/headless-cp-wf/blob/main/conf/slurm.config).

## 3. Download the container image once

Compute nodes often have no internet. Run a small test once where you have internet and the same storage,
for example in an interactive job. It puts the CellProfiler image into `container_cache`:

```bash
nextflow run . -profile test,apptainer --container_cache /<shared storage>/containers
```

## 4. Test your setup

Test the setup in a short interactive job, before you submit a large run. Do not use the login node.
First a dry run. The jobs make small fake files instead of running CellProfiler, but Nextflow still sends
each job to Slurm. Thus it tests your account, your partition and your `site.config`:

```bash
nextflow run . -profile test,slurm,apptainer -c site.config -stub-run
```

It must end with `[SUCCESS] completed=5 failed=0 cached=0`. Then run the real test with CellProfiler:

```bash
nextflow run . -profile test,slurm,apptainer -c site.config
```

The tables in `results_test/features/` must have 6 image sets and 51 nuclei. If the numbers differ, do not
start a large run. Find the cause first, with [Troubleshooting](troubleshooting.md).

## 5. Run Nextflow as a job

Do not run Nextflow on the login node. Run it as a long Slurm job with few resources. Nextflow then submits
one job per chunk:

```bash title="run.sbatch"
#!/bin/bash
#SBATCH -A <account> -p <cpu partition> -c 2 -t 3-00:00:00 -J cp-headless
nextflow run /<shared storage>/headless-cp-wf \
    -profile slurm,apptainer -c site.config -params-file params.yml \
    -work-dir /<shared storage>/work/plate1 -resume
```

- Put the work folder (`-work-dir`) on shared storage that all nodes can read.
- Start each run from the same folder, so that `-resume` finds its cache.
- If the job stops (for example at its time limit), submit it again. `-resume` continues the run.

## 6. After the run

Check the results as described in [Output](../output.md). Then remove the work folder, because it holds many
small files. Keep it only while you need `-resume`.
