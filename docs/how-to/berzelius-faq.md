# Berzelius FAQ

This page answers common questions about cores, memory, cost and job placement on Berzelius.
For the steps to run the workflow, see [Run on Berzelius](run-on-hpc.md).

The numbers in the answers apply when you use the suggested settings for a full screen:

```bash
sbatch -A <account> scripts/berzelius-run.sbatch <images> <project_name> 9 \
    --task_memory '7 GB' --task_time 2h --max_jobs 64
```

## Cores and memory

### How many cores and how much memory does each task get?

Each task gets 1 core, 7 GB of memory and a time limit of 2 hours.
Each task runs on one node.

| Setting | Value | Option |
|---|---|---|
| Cores | 1 | `--task_cpus` (default 1) |
| Memory | 7 GB | `--task_memory` (default 6 GB) |
| Time limit | 2 hours | `--task_time` (default 4 hours) |

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
- `--max_jobs` sets the maximum number of tasks at the same time. With 64 tasks, the maximum is 64 cores and 448 GB.

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

All users share the 8 CPU nodes. Ask your group before you use more than 64.

### What does the head job do and what does it use?

The head job runs Nextflow. Nextflow submits the tasks to Slurm, watches them and starts the next steps.
The head job does not run CellProfiler.

| Resource | Value |
|---|---|
| Cores | 2 |
| Memory | about 15.5 GB (the Slurm default for 2 cores) |
| Nextflow memory | at most 4 GB (`NXF_OPTS='-Xms512m -Xmx4g'`) |
| Time limit | 72 hours. Submit the same command again to continue. |

## Software and setup

### Must Nextflow and CellProfiler use the same Python version?

No. Nextflow is a Java program. It does not use Python.
CellProfiler uses Python 3.9 and Java (for image reading). Nextflow uses the same Java.
The tasks use the `cellprofiler` and `python` commands of the environment that starts Nextflow.
For this reason, the setup puts both tools in one environment.

### Why must I load the module before I install the environment?

The `conda` and `mamba` commands are available only after `module load Miniforge3/25.3.1-0`.
On Berzelius, `mamba install` also needs the environment path, for example `-p /proj/<project>/users/$USER/envs/cp-headless`.
See [Set up once](run-on-hpc.md#set-up-once).

## Stopped runs

### If ILLUMINATION is complete and ANALYSIS stops, does ILLUMINATION run again?

No. Both scripts use `-resume`. Submit the same command again.
Nextflow keeps the illumination results and continues with ANALYSIS.
Some changes make steps run again. See [Continue a stopped run](run-on-hpc.md#continue-a-stopped-run).
