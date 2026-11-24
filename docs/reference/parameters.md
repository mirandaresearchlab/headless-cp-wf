# Workflow parameters

This reference is generated from `nextflow.config` and both profile files on every documentation build.

Use `--name value` for these parameters. `null` means no explicit value.
Defaults below are configuration values. Descriptions explain path fallbacks and scope.

| Parameter | Local default | Berzelius default | Meaning |
|---|---|---|---|
| `--input` | `null` | `null` | Required samplesheet CSV with one row per image file. See file formats. |
| `--configs` | `null` | `null` | Required folder containing the two named pipeline files. |
| `--outdir` | `'.'` | `'.'` | Parent of projects/. |
| `--project` | `null` | `null` | Output project name. Defaults to the session ID. Existing names owned by another session fall back to that ID. |
| `--batch_size` | `9` | `9` | Positive number of complete image sets per analysis task. |
| `--segmentation` | `'cpu'` | `'cpu'` | Where SEGMENT runs RunCellpose (Cellpose-SAM): cpu or gpu. Used only if 2_analysis.cppipe has RunCellpose. ANALYSIS always runs on CPUs. |
| `--segmentation_batches` | `0` | `0` | Analysis batches in one SEGMENT task. 0: 16 with --segmentation gpu (larger groups keep a GPU busy), 1 with cpu. |
| `--segmentation_workers` | `4` | `4` | Positive number of CellProfiler processes in one SEGMENT task. On a GPU they share it: 4 keep an A100 80% busy, 8 about 89% (3.8 GB GPU memory each). On a CPU each gets one core and task_memory. |
| `--cellpose_models` | `null` | `null` | Folder with the Cellpose-SAM model file cpsam. Default: ~/.cellpose/models. A missing file is downloaded once (1.2 GB). |
| `--task_cpus` | `1` | `1` | CPU request for each task. Library threads remain limited to one. |
| `--task_memory` | `'6 GB'` | `'6 GB'` | Memory request for each task. Must be positive and no larger than total_memory, on either profile. |
| `--task_time` | `'4h'` | `'4h'` | Time limit for each task. |
| `--max_retries` | `1` | `2` | Retry limit for task exit statuses 137 (memory), 140 (time limit) or 143 (cancel). Each retry multiplies task_memory and task_time by the attempt number, up to the profile limit (local: total_memory; Berzelius: 960 GB and 72 hours). |
| `--total_cpus` | `2` | `2` | Positive shared CPU budget for the local executor. |
| `--total_memory` | `'16 GB'` | `'16 GB'` | Shared memory budget for local execution. Also bounds task_memory during validation on both profiles. |
| `--max_forks` | `0` | `0` | Local per-process concurrency limit. Zero adds no limit beyond executor resources. |
| `--slurm_partition` | `'berzelius-cpu'` | `'berzelius-cpu'` | Slurm partition. Confirm access and the partition name with your cluster. |
| `--slurm_account` | `null` | `null` | Optional Slurm allocation account passed with --account. |
| `--max_jobs` | `8` | `8` | Maximum submitted/active tasks managed by the Slurm executor. |
| `--shared_dir` | `null` | `null` | Berzelius root for the default work folder. Supply it or --nf_work_dir. |
| `--gpu_partition` | `'berzelius'` | `'berzelius'` | Slurm partition for SEGMENT with --segmentation gpu. Each task requests one GPU. |
| `--gpu_cpus` | `16` | `16` | Cores of one SEGMENT task with --segmentation gpu: the cores that come with one GPU (16 on Berzelius Ampere, 14 on Hopper). |
| `--max_gpus` | `4` | `4` | Most SEGMENT tasks, and so GPUs, at the same time with --segmentation gpu on Slurm. |
| `--nf_work_dir` | `null` | `null` | Work folder. Local default: launchDir/work. Berzelius default: shared_dir/nextflow-work. |

Nextflow options use one dash: `-profile local`, `-profile berzelius`, and `-resume SESSION_ID`.
There is no workflow `--help` page or test profile. See [usage](../usage.md) for complete commands.
See [resources](resources.md) for concurrency and [troubleshooting](../how-to/troubleshooting.md) for failures.
