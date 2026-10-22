# Berzelius: interactive run

This page shows how to run the workflow on your data inside an interactive job on Berzelius. You ask
Slurm for one CPU node (or part of it). All CellProfiler jobs then run on that node, as many at once as its
cores allow. Nextflow submits no Slurm jobs. Use this way for tests and for small runs.

!!! info "Before you start"
    Do [Berzelius: set up](berzelius-setup.md) first, including the test (step 5) and your params file
    (step 6). For large runs, see [Berzelius: batch run](berzelius-batch.md).

!!! note "Testing status"
    `run_interactive.sh` uses the same method as `smoke_test.sh`, which ran on Berzelius on 2026-10-15. The
    tests of the workflow run `run_interactive.sh` with fake Slurm settings. We also ran it with a real
    Nextflow (dry run, on a computer without Slurm). No one ran `run_interactive.sh` on Berzelius yet.

## When to use it

| | Interactive run | Batch run |
| --- | --- | --- |
| Where the CellProfiler jobs run | On the one node of your interactive job | Each chunk in its own Slurm job, on any CPU node |
| How long it can run | The time that you ask for with `-t` | 72 hours per head job, and you can continue it |
| What your project pays | All cores of the interactive job, for the whole time, also when they wait | Only the cores of the jobs that run |
| If your connection breaks | The interactive job can end. Run the same command again: it continues. | The run goes on. |

## Step 1. Start an interactive job

On a login node, ask for a CPU node. Each analysis chunk uses `--segmentation_cpus` cores (2) with 7 GB each,
and each ILLUM job 1 core and 7 GB. So 16 cores run 8 chunks at the same time:

```bash
interactive -A <project-account> -p berzelius-cpu -n 1 -c 16 -t 04:00:00
```

Use `-p berzelius-hopper-cpu` on the Hopper system. Choose `-t` longer than the run needs. A job starts a
new shell, so set `PROJ` again and go to the code:

```bash
export PROJ=/proj/<project>/users/$USER
cd "$PROJ/cp-headless"
```

## Step 2. Run the workflow

```bash
bash scripts/berzelius/run_interactive.sh "$PROJ/cp-headless.env" "$PROJ/runs/panc1.yml" "$PROJ/runs/panc1"
```

| Argument | Meaning |
| --- | --- |
| 1st | Your settings file ([setup, step 4](berzelius-setup.md#step-4-make-your-settings-file)) |
| 2nd | Your params file ([setup, step 6](berzelius-setup.md#step-6-write-the-parameters-of-your-run)) |
| 3rd | The run folder in `/proj`. It holds the work files and the cache for `-resume`. |
| `-- ...` | More options for `nextflow run`, for example `-- --chunk_size 20` |

The script first checks that it runs inside a job on a CPU partition. Then it writes `interactive.config` in
the run folder. This file makes Nextflow run the jobs on this node (local executor), with the cores and the
memory of your job (7 GB per core); they also become `--total_cpus` and `--total_memory` of the run. Then it
starts Nextflow with `-profile berzelius` and `-resume`. The
first line shows the cores and the memory:

```text
Interactive run in job <jobid> on <node>: 16 cores, 112 GB, run folder /proj/<project>/users/<user>/runs/panc1
```

The log of Nextflow appears on the screen. When the run ends, leave the job with `exit`.

## Step 3. Continue a stopped run

The job can end before the run, for example at its time limit, after a broken connection or after an error.
Then start a new interactive job and run the same command of step 2 again. Nextflow continues with `-resume`. It does not run the finished chunks
again. Always use the same run folder.

For a run that takes longer than an interactive job can give, use a [batch run](berzelius-batch.md) with
the same params file.

## After the run

See [After a run](berzelius-setup.md#after-a-run). The trace file of an interactive run is
`pipeline_info/trace.txt` in your `outdir`.

## Troubleshooting

| Message | Cause and solution |
| --- | --- |
| `run this inside an interactive job on a CPU node, not on a login node` | Start the interactive job of step 1 first. |
| `this job runs in partition '...'. Use berzelius-cpu or berzelius-hopper-cpu.` | The job is on a GPU partition. End it with `exit` and ask for a CPU partition (step 1). |
| `RUN_DIR ... is in your home directory` | Use a run folder in `/proj`. |
| Jobs wait and run one after the other | The job has few cores. Ask for more cores with `-c` in step 1. |
| `--segmentation_cpus 2 is more than --total_cpus 1` | The job has 1 core, but a chunk needs 2. Ask for at least 2 cores with `-c`. |
| Other messages | See [setup: troubleshooting](berzelius-setup.md#troubleshooting) and [Troubleshooting](troubleshooting.md). |
