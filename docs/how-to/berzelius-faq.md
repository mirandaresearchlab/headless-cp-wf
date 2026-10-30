# Berzelius FAQ

This page answers common questions about cores, memory, cost and job placement on Berzelius.
For the steps to run the workflow, see [Run on Berzelius](run-on-hpc.md).

The numbers in the answers apply when you use the suggested settings for a full screen:

```bash
sbatch -A <account> scripts/berzelius-run.sbatch <images> <project_name> 9 \
    --task_memory '7 GB' --task_time 4h --max_jobs 96
```

## Cores and memory

### How many cores and how much memory does each task get?

Each task gets 1 core, 7 GB of memory and a time limit of 4 hours.
Each task runs on one node.

| Setting | Value | Option |
|---|---|---|
| Cores | 1 | `--task_cpus` (default 1) |
| Memory | 7 GB | `--task_memory` (default 6 GB) |
| Time limit | 4 hours | `--task_time` (default 4 hours) |

All five steps get the same values: PREPARE, ILLUMINATION, ANALYSIS, MERGE and CONCAT.

### Why does each task use only one core?

CellProfiler uses one core. The workflow also limits the maths libraries to one thread.
A second core does nothing, but Berzelius charges you for it.
To make a run faster, run more tasks at the same time. Use `--max_jobs` for this.

### Why 7 GB of memory?

In a benchmark run, the largest ANALYSIS task used 5.0 GB. 7 GB gives about 2 GB of extra space.
Berzelius charges memory in units of about 7.7 GB. A task with 7 GB and 1 core costs the same as 1 core.
See [How does Berzelius charge for cores and memory?](#how-does-berzelius-charge-for-cores-and-memory)

The memory of a task does not increase with the batch size.
CellProfiler analyses one image set at a time.
MERGE holds one batch of tables in memory. Keep the batch size at about 9.

### Do I need a total memory limit for the batch job?

No. Each task is its own Slurm job, and Slurm controls the memory of each job:

- Slurm starts a job only on a node that has 7 GB free.
- Slurm stops a task that uses more than its 7 GB. Other tasks are not affected.
- `--max_jobs` sets the maximum number of tasks at the same time. With 96 tasks, the maximum is 96 cores and 672 GB.

`--total_memory` limits the memory only in an interactive session.
In a batch job, the workflow uses it only to check that `--task_memory` is not larger.

### What does Slurm give to a job that does not ask for memory?

Slurm gives 7950 MB (about 7.8 GB) for each core. This is the `DefMemPerCPU` setting.
The workflow tasks always ask for memory, so they get the value of `--task_memory`.
The head job does not ask for memory. It gets 2 × 7950 MB, about 15.5 GB.

To see the current value, run:

```bash
scontrol show config | grep DefMemPerCPU
```

### What happens when a task uses too much memory?

Slurm stops the task with exit status 137.
The workflow tries the task again with the same memory, so the retry usually fails too.

1. Read `report/trace.txt` to find the task and its peak memory (`peak_rss`).
2. Submit the same command again with more memory, for example `--task_memory '14 GB'`.

Nextflow keeps the completed tasks. Only the failed tasks and the remaining tasks run with the new value.

## Cost

### How does Berzelius charge for cores and memory?

Berzelius charges each job for the larger of two values:

- the number of cores
- the memory divided by about 7.7 GB

| Cores | Memory | Charged as |
|---|---|---|
| 1 | 6 GB | 1 core |
| 1 | 7 GB | 1 core |
| 1 | 14 GB | 1.8 cores |
| 2 | 7 GB | 2 cores |

To see the current settings, run:

```bash
scontrol show partition berzelius-cpu | grep -o 'TRESBillingWeights=[^ ]*'
scontrol show config | grep PriorityFlags   # MAX_TRES means "the larger of"
```

### Does a higher `--max_jobs` cost more?

No. The total core-hours stay the same. More tasks at the same time only make the run finish sooner.
For an estimate, see [Estimate the run time and the cost](run-on-hpc.md#estimate-the-run-time-and-the-cost).

### Why does an interactive session cost more than a batch job?

Berzelius charges every core of an interactive session for the full time that the session is open.
At the end of a run, only MERGE and CONCAT run, and most cores do nothing.
A batch job charges only for the tasks that run.

## Where tasks run

### Does Slurm put all tasks on one node?

Not in a batch job. Slurm puts each task on any CPU node that has 1 free core and 7 GB free.
There are 8 CPU nodes (`node221` to `node228`). The tasks can be on one node or on many nodes.

This works because:

- The images, the work folder, the environment and the results are in `/proj`. All nodes can read and write `/proj`.
- Slurm gives each task the same software environment as the head job.
- Each task reads its own files and writes its own files. Tasks do not communicate with each other.

In an interactive session, all tasks run on the one node of the session.

### Can one task use more than one node?

No. One task always runs on one node, on one core.
Slurm divides the work between nodes only by task.

### How many tasks run at the same time?

| Mode | Maximum number of tasks at the same time |
|---|---|
| Interactive session | The number of cores in the session (`-c`). One node has 128 cores. |
| Batch job | `--max_jobs` (default 8) |

All users share the 8 CPU nodes. Ask your group before you use more than 96.

### What does the head job do and what does it use?

The head job runs Nextflow. Nextflow submits the tasks to Slurm, watches them and starts the next steps.
The head job does not run CellProfiler.

| Resource | Value |
|---|---|
| Cores | 2 |
| Memory | about 15.5 GB (the Slurm default for 2 cores) |
| Nextflow memory | at most 4 GB (`NXF_OPTS='-Xms512m -Xmx4g'`) |
| Time limit | 72 hours. Submit the same command again to continue. |

### Which nodes do my jobs use?

Run this command. The last column shows the node of each running job:

```bash
squeue -u $USER -o "%.10i %.25j %.3t %.10M %R"
```

To count the running tasks on each node, run:

```bash
squeue -u $USER -t R -h -o "%N" | sort | uniq -c
```

For jobs that are complete, run `sacct -u $USER -S today --format=JobID,JobName%25,State,Elapsed,NodeList`.

## Submitted jobs

### Can I log out after I submit the job?

Yes. `sbatch` jobs run on the compute nodes, not in your terminal.
You can close the terminal, log out or shut your laptop. The job continues.
This is not true for an interactive session. It ends when you leave.

Before you leave, run `squeue -u $USER`. The head job must be in the list with `R` (running) or `PD` (waiting).

### How long does the run take?

Add the time of each plate. For plates of 3,420 image sets with `--max_jobs 96`, one plate takes about 4 to 5 hours of computing time.
The estimate has a formula: see [Estimate the run time and the cost](run-on-hpc.md#estimate-the-run-time-and-the-cost).
Time in the queue is not included.

## Disk space

### How much disk space is free?

Run `nscquota`. The line for your project shows the used space, the quota and the hard limit.
The quota is the limit to use for planning. Above the quota, the project has only a short grace period.
The `df` command shows the hard limit, so it shows more free space than you can use.

### What if the project does not have enough space for all plates?

Run the plates one after another with `scripts/berzelius-run-plates.sbatch`.
It deletes the work files of each plate after the plate is complete.
See [Run one plate at a time](run-on-hpc.md#run-one-plate-at-a-time-when-disk-space-is-short).

## Software and setup

### Do I need to provide the CellProfiler pipelines?

Yes. You provide `1_illumination.cppipe` and `2_analysis.cppipe`, made for your images.
The files in `cp-configs` are examples for one screen with five channels. They may not fit your images.
The folder must contain exactly these two `.cppipe` files.
See [Provide your own pipelines](../usage.md#provide-your-own-pipelines) and [Before you start](run-on-hpc.md#before-you-start).

### Must Nextflow and CellProfiler use the same Python version?

No. Nextflow is a Java program. It does not use Python.
CellProfiler uses Python 3.9 and Java (for image reading). Nextflow uses the same Java.
The tasks use the `cellprofiler` and `python` commands of the environment that starts Nextflow.
For this reason, the setup puts both tools in one environment.

### Why must I load the module before I install the environment?

The `conda` and `mamba` commands are available only after `module load Miniforge3/25.3.1-0`.
On Berzelius, `mamba install` also needs the environment path, for example `-p /proj/<project>/users/$USER/envs/cp-headless`.
See [Set up once](run-on-hpc.md#set-up-once).

## When a job stops or fails

### What happens when a job stops early or fails?

Nextflow keeps the work of every task that finished. The next run reuses it.

| What happened | What happens to the run | What you do |
|---|---|---|
| A task fails. For example, it reaches its time limit (exit status 140). | Nextflow stops the run. It cancels the tasks that are still running or waiting. | Find the failed task in the log. Fix the cause. Submit the same command. |
| Slurm stops a task for memory (exit status 137), or someone cancels a task (exit status 143) | Nextflow tries the task again, up to 2 times, with the same memory. If it fails again, the run stops. | Increase `--task_memory`. Submit the same command. |
| The head job reaches its 72-hour limit, or you cancel it with `scancel` | The run stops. Finished tasks stay saved. | Run `squeue -u $USER`. Cancel task jobs that remain. Submit the same command. |
| An interactive session ends | The tasks in the session stop. | Start a new session. Run the same script command again. |

When Nextflow stops after a task failure, it cancels the other tasks.
The cancelled tasks show `CANCELLED` in `sacct`. They are not errors.
The head job ends with state `FAILED`.
Nextflow cancels its task jobs when a task fails. We did not test what happens to the task jobs when you cancel the head job with `scancel`. Check with `squeue`.

### How do I see why a job failed?

Read the end of the log of the head job (`cp-headless-<jobid>.log` or `cp-plates-<jobid>.log`).
Look for the text `Error executing process`. These lines follow it:

| Line | What it tells you |
|---|---|
| `Error executing process > 'ANALYSIS (<plate>/batch_0014)'` | The step and the batch that failed |
| `terminated with an error exit status (140)` | The exit status |
| `Work dir:` | The folder with the files of this task. `.command.log` and `.command.err` in it show the output. |

The exit status tells you the cause:

| Exit status | Cause | Fix |
|---|---|---|
| 137 | Slurm stopped the task because it used more memory than `--task_memory`. | Increase `--task_memory`. |
| 140 | The task ran longer than `--task_time`. | Increase `--task_time`. |
| 143 | Slurm or a user cancelled the task. | Check why. Submit the same command. |
| Other | The task itself failed. | Read `.command.err` in the work folder. |

To see the job details, run:

```bash
sacct -u $USER -S today --format=JobID,JobName%40,State,Elapsed,Timelimit,ExitCode
```

A task that reached its time limit can show `FAILED` and not `TIMEOUT`. Compare `Elapsed` with `Timelimit`.
If they are almost the same, the task reached its time limit.

### What stays on disk after a failure?

| What | State after a failure |
|---|---|
| Work files of the finished tasks | Kept in the work folder. The next run reuses them. |
| Masks and logs of the finished ANALYSIS tasks | Kept in the results folder. |
| Final table (`all_plates.csv.gz`) | Not written. MERGE and CONCAT write it at the end of a plate. |
| `DONE` file of the plate script | Not written. The script writes it only after a plate succeeds. |
| Work files of the failed plate (plate script) | Kept. The script deletes them only after a plate succeeds. |

The work files use quota. Delete the work folder only when you do not need to resume the run.

### How do I restart after a failure?

1. Fix the cause. For example, increase `--task_time` or `--task_memory`.
2. Check that the folders from the first run are still there: the work folder and the `-launch` folder.
3. Submit the same command as before. Change only the setting that caused the failure.

For the plate script, use the same `DATA` and `OUT`. A different `OUT` starts every plate again.
The script skips the plates that have a `DONE` file and resumes the plate that failed.
It does not start the next plate while a plate fails.

Changing `--task_time`, `--task_memory` or the number of cores does not make finished tasks run again.
See [Continue a stopped run](run-on-hpc.md#continue-a-stopped-run) for the changes that do.

### Do I pay for a task that fails?

Yes. Berzelius charges the cores for the time that a job ran, also when it fails or you cancel it.
A task that reaches a time limit of 2 hours costs 2 hours of one core.

### What happened in a real run?

A run used three plates of 17,100 images each, with `--task_time 2h`.
Plate 1 and plate 2 finished. Their tasks took 41 to 47 minutes on average.
The tasks of plate 3 took longer: 57 minutes on average and up to 113 minutes.
Two tasks reached the 2-hour limit and failed with exit status 140. Nextflow stopped the run and cancelled 93 other tasks.
133 tasks of plate 3 finished before the stop. A new run with `--task_time 4h` should reuse them. We did not test this yet.

### If ILLUMINATION is complete and ANALYSIS stops, does ILLUMINATION run again?

No. Both scripts use `-resume`. Submit the same command again.
Nextflow keeps the illumination results and continues with ANALYSIS.
Some changes make steps run again. See [Continue a stopped run](run-on-hpc.md#continue-a-stopped-run).
