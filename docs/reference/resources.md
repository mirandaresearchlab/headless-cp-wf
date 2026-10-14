# Resources

This page lists the CPU cores, memory and time that each job asks for. `task.attempt` is 1 for the first try
and 2, 3, 4 for each new try after a memory or time error.

## Default (all profiles except `berzelius`)

| Job | Cores | Memory | Time |
| --- | --- | --- | --- |
| PATCH_PIPELINE (once) | 1 | 2 GB × attempt | 30 min × attempt |
| CELLPROFILER (one per chunk) | 1 | 8 GB × attempt | 6 h × attempt |
| MERGE_FEATURES (once) | 1 | 4 GB × attempt | 2 h × attempt |

## `berzelius` profile

Slurm on Berzelius charges each core, and gives about 7.7 GB of memory per core. Thus each job asks for at
most 7 GB per core.

| Job | Cores | Memory | Time |
| --- | --- | --- | --- |
| PATCH_PIPELINE | 1 | 2 GB × attempt | 30 min × attempt |
| CELLPROFILER | 1 × attempt | 7 GB × attempt | 6 h × attempt |
| MERGE_FEATURES | 1 × attempt | 7 GB × attempt | 4 h × attempt |

## Limits and new tries

- Exit codes 104, 134, 137, 139, 140 and 143 mean that a job used too much memory or time. Such a job gets
  up to 3 new tries. Other errors stop the run after the running jobs finish.
- No job asks for more than `--max_cpus`, `--max_memory` and `--max_time`. The defaults are 16 cores, 64 GB and 48 h.
  On Berzelius they are 16 cores, 112 GB and 72 h.

## Measured on the test data

From `pipeline_info/trace.txt` of the [tutorial](../tutorials/first-run.md) run (Docker on Apple Silicon,
emulated amd64):

| Job | Time | Peak memory |
| --- | --- | --- |
| PATCH_PIPELINE | 1.8 s | 183 MB |
| CELLPROFILER (2 image sets of 128 × 128 pixels) | 4.2 to 4.4 s | 370 to 385 MB |
| MERGE_FEATURES | 0.15 s | 6 MB |

Real images are larger. Measure the time and memory on one plate (`trace.txt`, columns `realtime` and
`peak_rss`), then choose `--chunk_size` and `--max_memory`.
