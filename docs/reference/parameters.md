# Workflow parameters

This reference is generated from `nextflow.config` and both profile files on every documentation build.

Use `--name value` for these parameters. `null` means no explicit value.
Defaults below are configuration values. Descriptions explain path fallbacks and scope.

| Parameter | Local default | Berzelius default | Meaning |
|---|---|---|---|
| `--images` | `null` | `null` | Required image root containing one folder per plate. |
| `--configs` | `null` | `null` | Required folder containing the two named pipeline files. |
| `--project` | `null` | `null` | Output project name. Defaults to the session ID. Existing names owned by another session fall back to that ID. |
| `--outdir` | `'.'` | `'.'` | Parent of projects/. Must keep the resolved output outside the image root. |
| `--batch_size` | `9` | `9` | Positive number of complete image sets per analysis task. |
| `--task_cpus` | `1` | `1` | CPU request for each task. Library threads remain limited to one. |
| `--task_memory` | `'6 GB'` | `'6 GB'` | Memory request for each task. Must be positive and no larger than total_memory, on either profile. |
| `--task_time` | `'4h'` | `'4h'` | Time limit for each task. |
| `--total_cpus` | `2` | `2` | Positive shared CPU budget for the local executor. |
| `--total_memory` | `'16 GB'` | `'16 GB'` | Shared memory budget for local execution. Also bounds task_memory during validation on both profiles. |
| `--max_forks` | `0` | `0` | Local per-process concurrency limit. Zero adds no limit beyond executor resources. |
| `--max_jobs` | `8` | `8` | Maximum submitted/active tasks managed by the Slurm executor. |
| `--nf_work_dir` | `null` | `null` | Work directory override. Local fallback: launchDir/work. Berzelius fallback: shared_dir/nextflow-work. |
| `--conda_cache` | `null` | `null` | Conda cache path. Local fallback: launchDir/.nextflow/conda. Berzelius fallback: shared_dir/conda-cache. No tasks currently declare a Conda environment. |
| `--shared_dir` | `null` | `null` | Berzelius root for default work and Conda cache paths. Supply it or both explicit paths. |
| `--slurm_partition` | `'berzelius-cpu'` | `'berzelius-cpu'` | Slurm partition. Confirm access and the partition name with your cluster. |
| `--slurm_account` | `null` | `null` | Optional Slurm allocation account passed with --account. |
| `--max_retries` | `1` | `2` | Retry limit for task exit statuses 137 or 143. Resources do not increase on retry. |

Nextflow options use one dash: `-profile local`, `-profile berzelius`, and `-resume SESSION_ID`.
There is no workflow `--help` page or test profile. See [usage](../usage.md) for complete commands.
See [resources](resources.md) for concurrency and [troubleshooting](../how-to/troubleshooting.md) for failures.
