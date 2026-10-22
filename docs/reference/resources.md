# Resources

This page lists the CPU cores, memory and time that each job asks for, and how many jobs run at once.
`task.attempt` is 1 for the first try and 2, 3, 4 for each new try after a memory or time error.

## Default (all profiles except `berzelius`)

| Job | Cores | Memory | Time |
| --- | --- | --- | --- |
| PATCH_PIPELINE (once per pipeline) | 1 | 2 GB × attempt | 30 min × attempt |
| ILLUM (one per plate) | 1 | 8 GB, doubled on each new try | 4 h × attempt |
| CELLPROFILER (one per chunk) | `--segmentation_cpus` (2) | `--memory_per_cpu` (4 GB) × cores, doubled on each new try | 12 h × attempt |
| MERGE_FEATURES (once) | 1 | 4 GB × attempt | 2 h × attempt |

These are starting values. After the first run on real data, set them from `pipeline_info/trace.txt`: memory =
the highest `peak_rss` of the job type + 25 %. ILLUM averages the images one by one, so its memory does not
grow with the size of the plate.

## `berzelius` profile

Slurm on Berzelius charges each core, and gives about 7.7 GB of memory per core. Thus each job asks for at
most 7 GB per core, and gets more cores when it needs more memory.

| Job | Cores | Memory | Time |
| --- | --- | --- | --- |
| PATCH_PIPELINE | 1 | 2 GB × attempt | 30 min × attempt |
| ILLUM | 1, doubled on each new try | 7 GB, doubled on each new try | 4 h × attempt |
| CELLPROFILER | `--segmentation_cpus` (2), doubled on each new try | 7 GB × cores (14 GB at 2 cores) | 12 h × attempt |
| MERGE_FEATURES | 1 × attempt | 7 GB × attempt | 4 h × attempt |

## How many jobs run at once

One run handles all plates. The limits count the jobs of all plates together.

| Executor | Limit |
| --- | --- |
| local (workstation, interactive job) | Nextflow starts a job only when its cores are free within `--total_cpus` (default 8), and its memory within `--total_memory` (default: all memory of the computer). |
| Slurm, Berzelius | At most `--total_cpus / --segmentation_cpus` jobs are in the queue or running (`executor.queueSize`). The `slurm` profile uses `--total_cpus 200` (100 jobs), the `berzelius` profile `--total_cpus 64` (32 jobs). |

The run stops at once if `--segmentation_cpus` is more than `--total_cpus` or `--max_cpus`. The log shows how
many chunks can run at once, and for each plate its chunks, cores and memory:

```text
cores          : 2 per chunk, 8 in total -> 4 chunk(s) at once
[cp-headless] PANC1_P01: 3456 image set(s) of 5 file(s), 70 chunks x 2 cores x 8 GB
```

| `--total_cpus` | `--segmentation_cpus` | Chunks at once | Memory in use (default `--memory_per_cpu`) |
| --- | --- | --- | --- |
| 8 | 2 | 4 | 32 GB (8 GB each) |
| 16 | 2 | 8 | 64 GB (8 GB each) |
| 16 | 4 | 4 | 64 GB (16 GB each) |

## Limits and new tries

- Exit codes 104, 134, 137, 139, 140 and 143 mean that a job used too much memory or time. Such a job gets
  up to 3 new tries. Other errors stop the run after the running jobs finish.
- No job asks for more than `--max_cpus`, `--max_memory` and `--max_time`, and no job asks for more cores than
  `--total_cpus`. The defaults are 16 cores, 64 GB and 48 h. On Berzelius they are 16 cores, 112 GB and 72 h.

## Measured on the test data

From `pipeline_info/trace.txt` of the [tutorial](../tutorials/first-run.md) run (Docker on Apple Silicon,
emulated amd64), before the plate layout (version 1.0):

| Job | Time | Peak memory |
| --- | --- | --- |
| PATCH_PIPELINE | 1.8 s | 183 MB |
| CELLPROFILER (2 image sets of 128 × 128 pixels) | 4.2 to 4.4 s | 370 to 385 MB |
| MERGE_FEATURES | 0.15 s | 6 MB |

Real images are larger, and Cellpose and the measurements of a Cell Painting pipeline take minutes per site.
Measure the time and memory on one plate (`trace.txt`, columns `realtime` and `peak_rss`), then choose
`--chunk_size`, `--memory_per_cpu` and `--max_memory`.
