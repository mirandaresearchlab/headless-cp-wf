# Troubleshoot a failed or unexpected run

Start with the first failed task and its error message.

## Find the useful logs

1. Read `.nextflow.log` in the folder where you launched Nextflow.
2. Find the failed process name and its work directory in the error message.
3. Open `.command.err`, `.command.out`, and `.command.log` inside that work directory, when present.
4. For CellProfiler failures, read `result/logs/*.log` in the same work directory.

Successful tasks publish logs under the project folder.
Failed tasks may leave their only detailed logs in the work directory.
`trace.txt` shows task status and exit codes. Project status files record the overall outcome.
Do not delete work files while investigating a failure.

## Symptoms and fixes

| Symptom or error | Likely cause | Action |
|---|---|---|
| `nextflow`, `python`, or `cellprofiler` not found | Missing tool or inactive environment | Follow [installation](../getting-started/installation.md). Activate `cp-headless` before launching. |
| Java version or startup error | Nextflow sees an incompatible Java | Check the launcher's Java. Set `NXF_JAVA_HOME` to a supported installation if needed. |
| `Require cellprofiler=4.2.8.1` | Different CellProfiler version | Recreate the environment from `environment.yml`. Check both CellProfiler package versions. |
| Conda cannot solve the environment | Package availability, platform, channel, or network problem | Save the complete solver error. Check the supported platform and channels. Do not silently relax pinned versions. |
| Missing input folder | Incorrect path or broken data link | Check `--images`, `--configs`, and any symlink targets. Obtain test data separately if needed. |
| `No TIFF inputs found` | Empty folder, hidden files, or wrong root | Point `--images` at the parent of the plate folders. Check extensions and visibility. |
| `Expected images/<plate>/<filename>.tiff` | Wrong folder depth | Put each TIFF directly inside a plate folder. |
| Requires exactly two pipelines | Missing, extra, or differently named `.cppipe` files | Use the two names listed in [usage](../usage.md). |
| `unmatched filename` | Filename does not match pipeline metadata rules | Compare it with the [configured rule](../reference/file-formats.md). Check extension and channel spelling. |
| `missing channels`, `unknown channel`, `duplicate channel` | Incomplete or conflicting image set | Restore the correct files. Check channel mapping in both pipelines. |
| `ambiguous image set` | Different acquisitions share the configured matching keys | Review metadata and matching rules. Do not combine distinct acquisitions. |
| `Expected single-plane grayscale TIFF` or `Unsupported TIFF dtype` | Stack, RGB, float, or other unsupported layout | Export one 2D unsigned 8-bit or 16-bit grayscale TIFF per channel. Check the conversion preserves scientific values. |
| `All images in a plate must share dimensions` | Mixed image sizes | Correct the plate contents or image export. |
| Unsafe plate or image name | Unsupported characters or a reserved name | Follow the naming rules in [usage](../usage.md). |
| Output/work directory must be outside images | Results or work files are inside the input root | Choose separate output and work folders. |
| Invalid batch size or memory budget | Zero, negative, or inconsistent parameter | Use a positive integer batch size. Keep task memory within total memory, including on Slurm. |
| Project already exists warning | Another session owns the project name | Use the printed session-ID output folder, choose a new name, or resume the original session. |
| Exit 137, 143, or CellProfiler exit -9 | Memory kill, time limit, cancellation, or another external termination | Read system or Slurm records before deciding. Follow the resource procedure below. |
| `Illumination checksum mismatch` or plate mismatch | Changed or incorrect correction files | Preserve the files for inspection. Restore matching inputs or run a fresh project. Do not edit the checksum record. |
| Mask, area, count, provenance, or column validation error | Inconsistent output or unsupported pipeline change | Stop using the affected results. Retain the work directory and reports. Reproduce with the supplied pipelines. |
| Many cells have blank cytoplasm measurements | Some cells have no cytoplasm pixels | Read [empty-cytoplasm behavior](../output.md#interpret-the-per-cell-table) and inspect the masks. |
| Final CSV is absent but masks exist | Analysis completed before a later failure | Check MERGE and CONCAT status. Masks alone do not prove run success. |
| Resume repeats work | Missing cache/output, changed inputs, or changed settings | Restore the original paths and options. CONCAT may repeat because its table was moved. |
| Berzelius requests shared storage | Missing required paths | Set `--shared_dir`, or both `--nf_work_dir` and `--conda_cache`. |
| Slurm jobs remain pending | Allocation, partition, or resource availability | Inspect the scheduler reason. Confirm your account and partition with the cluster administrator. |
| `Fixture destination already exists` | Tutorial crop folder already exists | Use the existing verified fixture or choose a new destination. |

## Resolve resource failures

First distinguish a task that needs more memory from too many simultaneous tasks.
Check task metrics, the HTML report, and scheduler records.
A missing peak-memory value does not rule out a memory kill.

For local memory pressure, reduce concurrent jobs with `total_cpus` or `max_forks`.
Set `total_memory` below the memory actually available to your process, leaving room for Nextflow and the operating system.
For one oversized task, raise `task_memory` and the total budget if the machine can support them.
For Slurm time limits, raise `task_time` within your allocation's limits.
Smaller batches reduce work per analysis job, but do not make a single image smaller.
Retries do not automatically raise memory or time.

Use the [resume guide](../usage.md#resume-a-run) after correcting the cause.
If old CellProfiler processes remain, identify the exact processes belonging to your stopped run before terminating them.
Do not kill all CellProfiler processes on a shared machine.

## Ask for help

Provide the launch command, software versions, first error, failed process name, and relevant logs.
Include the batch validation report and pipeline checksums when results fail validation.
Describe the image dimensions, channel set, and any pipeline changes.
Remove sensitive paths and sample names before sharing logs outside your group.
