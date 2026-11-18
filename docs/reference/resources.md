# Plan time, memory, and disk space

Use this page to choose resources before a large run.

## Current scheduling rules

Both profiles request 1 CPU, 6 GB memory, and 4 hours per task by default.
These requests apply to all five processes, including preparation and merging.
Numerical library threads are limited to one in `nextflow.config`.
Increasing `task_cpus` alone does not make CellProfiler use more threads.

The local profile shares 2 CPUs and 16 GB across tasks.
With default requests, at most two tasks fit that budget.
The approximate limit is the smaller of available CPUs divided by task CPUs,
and available memory divided by task memory. A task also needs ready inputs.
`max_forks` can further limit each process type.

The Berzelius profile submits up to eight tasks. Slurm decides when they start.
It does not use the local resource pool. However, the workflow still checks
that `task_memory` does not exceed `total_memory` on this profile.
Raise both values if a cluster task needs more than 16 GB.
See [all parameters](parameters.md).

Both profiles retain work files after success and failure.
Budget for input data, temporary tables, published results, and filesystem overhead.
The final combined table is moved to its published folder. Other temporary tables remain.

## Historical measurements

The figures below came from the previous repository README.
They were not measured again during this documentation update.
They describe one dataset, not a guarantee for your data or machine.
The original hardware details were not recorded.


Measured on a benchmark dataset (3 plates, 54 image sets, 2500 × 2500 pixels per image):

- **Per image set:** 5.0 to 6.0 minutes of analysis, on 1 CPU. Peak memory is 3.2 to 5.1 GB per task. 90% of the time is spent in measurement modules.
- **Illumination:** about 4 minutes per plate, or about 12 seconds per image set.
- **Whole run:** 29 minutes with `--total_cpus 16 --batch_size 4`, and 25 minutes with `--total_cpus 15 --batch_size 1`.

Treat these timings as a rough planning guide. Image size, object count, and measurements affect runtime.
More ready tasks can improve throughput when enough CPU and memory are available.
Reserve memory for Nextflow and the operating system, beyond the task budget.
Check container or scheduler limits as well as the host's physical memory.

A previous run used a 90 GB task pool and 15 CPUs within a 100 GB limit.
That example reserved about 10 GB for other processes. It is not a universal sizing rule.
Small batches can improve parallelism on small datasets, but add task startup overhead.

## Disk space

Measured on the same benchmark dataset, about 430 cells per image set:

| Data | Per image set |
|---|---|
| Raw images (input, 5 TIFFs) | 63 MB |
| `all_plates.csv.gz` | ~15 MB |
| Masks | ~1 MB |
| `work/` during the run (batch and plate tables) | ~28 MB, retained after success |

For example, 3 plates × 3,400 image sets need about 160 GB of output, plus about 290 GB in `work/` during the run. Use `--nf_work_dir PATH` to choose a disk with enough space. Replace `PATH` with your work folder.
