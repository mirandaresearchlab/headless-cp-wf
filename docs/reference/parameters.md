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
| `--task_cpus` | `1` | `1` | CPU request for each task. Library threads remain limited to one. |
| `--task_memory` | `'6 GB'` | `'6 GB'` | Memory request for each task. Must be positive and no larger than total_memory, on either profile. |
| `--task_time` | `'4h'` | `'4h'` | Time limit for each task. |
| `--max_retries` | `1` | `2` | Retry limit for task exit statuses 137 or 143. Resources do not increase on retry. |
| `--total_cpus` | `2` | `2` | Positive shared CPU budget for the local executor. |
| `--total_memory` | `'16 GB'` | `'16 GB'` | Shared memory budget for local execution. Also bounds task_memory during validation on both profiles. |
| `--max_forks` | `0` | `0` | Local per-process concurrency limit. Zero adds no limit beyond executor resources. |
| `--slurm_partition` | `'berzelius-cpu'` | `'berzelius-cpu'` | Slurm partition. Confirm access and the partition name with your cluster. |
| `--slurm_account` | `null` | `null` | Optional Slurm allocation account passed with --account. |
| `--max_jobs` | `8` | `8` | Maximum submitted/active tasks managed by the Slurm executor. |
| `--shared_dir` | `null` | `null` | Berzelius root for the default work folder. Supply it or --nf_work_dir. |
| `--nf_work_dir` | `null` | `null` | Work folder. Local default: launchDir/work. Berzelius default: shared_dir/nextflow-work. |

Nextflow options use one dash: `-profile local`, `-profile berzelius`, and `-resume SESSION_ID`.
There is no workflow `--help` page or test profile. See [usage](../usage.md) for complete commands.
See [resources](resources.md) for concurrency and [troubleshooting](../how-to/troubleshooting.md) for failures.
