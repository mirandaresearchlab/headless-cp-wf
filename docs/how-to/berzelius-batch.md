# Berzelius: batch run

This page shows how to run the workflow on Berzelius as a batch run. A small Slurm job, the **head job**,
runs Nextflow on a CPU node for 72 hours or less. Nextflow submits one Slurm job for each chunk of images,
on the CPU partition of your system. Use this way for large runs.

!!! info "Before you start"
    Do [Berzelius: set up](berzelius-setup.md) first, including the test (step 5) and your params file
    (step 6). For a small run on one node, see [Berzelius: interactive run](berzelius-interactive.md).

!!! note "Testing status"
    The tests of the workflow run `submit.sh` and `run_nextflow.sbatch` with fake `sbatch`, `squeue`,
    `nextflow` and `apptainer` programs. They also check the `#SBATCH` lines that Nextflow makes for each
    chunk. No one ran a batch run on Berzelius yet. Start with one small plate.

## Step 1. Start the run

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
| `-e` | Your settings file ([setup, step 4](berzelius-setup.md#step-4-make-your-settings-file)) |
| `-p` | Your params file ([setup, step 6](berzelius-setup.md#step-6-write-the-parameters-of-your-run)) |
| `-r` | The run folder in `/proj`. It holds the work files, the logs and the cache for `-resume`. |
| `-n` | Check only: show the `sbatch` command, but do not submit it |
| `-- ...` | More options for `nextflow run`, for example `-- --chunk_size 100` |

`submit.sh` first checks your settings. Then it submits one Slurm job, the **head job**. The head job runs
Nextflow on a CPU node with 2 cores for 72 hours or less. Nextflow submits the CellProfiler jobs. These jobs
use the same account and partition as the head job.

## Step 2. Follow the run

```bash
squeue -u "$USER"                             # your jobs in the queue
tail -f "$PROJ/runs/plate1/logs/head-<jobid>.out"   # the log of the head job
```

If a CellProfiler job fails, the log of the head job names its work folder, for example
`work/a6/dca722...`. Look in that folder at `.command.err` and `.command.log`. The log of CellProfiler is
`log_<chunk>.txt` in the same folder. To see how a Slurm job ended, run
`sacct -j <jobid> -o JobID,State,MaxRSS,Elapsed,ExitCode`. [Troubleshooting](troubleshooting.md) lists the
messages of the workflow, and [setup](berzelius-setup.md#troubleshooting) lists the messages of Berzelius.

## Step 3. Continue a stopped run

A head job stops after 72 hours. It also stops after an error. Run the same
`submit.sh` command again with the same run folder. Nextflow then continues with `-resume`. It does not run
the completed jobs again. `submit.sh` refuses to start a second head job in a run folder that has a running
head job.

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

After the run, read the results and remove the work files: see [After a run](berzelius-setup.md#after-a-run).
