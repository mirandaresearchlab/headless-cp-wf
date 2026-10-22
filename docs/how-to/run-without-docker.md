# Run without Docker

This guide shows how to run the workflow on a lab workstation without Docker. CellProfiler runs directly
on the workstation, with the `local` profile. The workstation is an Ubuntu system where you are `root`,
for example the container that you reach with SSH on a lab server.

!!! info "Before you start"
    Do [Installation](../getting-started/installation.md) first. This guide starts in the folder
    `headless-cp-wf`, after step 6 of that page.

!!! note "Testing status"
    We ran the steps of this guide as `root` in a clean Ubuntu 24.04 container (amd64, no Docker) on
    2026-10-15. The test gave 6 image sets and 51 nuclei. Every feature value was the same as in the
    official container, within a relative difference of 0.00001. The CI job `workstation-local` runs
    the same steps on each push. We did not run them on a lab server.

## How it differs from the container

The conda build of CellProfiler 4.2.8 uses newer libraries than the official container:

| Software | Official container | Conda environment of this guide |
| --- | --- | --- |
| Python | 3.8.0 | 3.9.19 |
| NumPy | 1.24.4 | 1.26.4 |
| Java for CellProfiler | 11.0.19 | 11.0.23 |

On the test data, both gave the same object counts. 113 of 4,233 feature values per table were different,
by at most 0.0008 % (a Zernike shape feature). Your own data can show other small differences. For results
that you compare with runs in the container, run both ways on a few images first.

## Step 1. Install CellProfiler

```bash
micromamba create -y -n cellprofiler -c conda-forge -c bioconda cellprofiler=4.2.8 openjdk=11
```

This takes some minutes. CellProfiler 4.2.8 needs Java 11, and Nextflow needs Java 17 to 26. Thus
CellProfiler has its own environment.

## Step 2. Activate CellProfiler

Run this line in each new terminal, after the lines of [Installation, step 5](../getting-started/installation.md#step-5-activate-nextflow):

```bash
export PATH="$MAMBA_ROOT_PREFIX/envs/cellprofiler/bin:$PATH"
```

Check both programs:

```bash
nextflow -version
cellprofiler --version
```

`nextflow -version` shows 26.04.6. `cellprofiler --version` shows `4.2.8.1` (the conda build). Before the
version, it can show some warning lines. They are harmless.

## Step 3. Give the jobs the Java of CellProfiler

Write a small settings file in the folder `headless-cp-wf`. It gives each job the Java 11 of the
`cellprofiler` environment. Nextflow itself keeps Java 21:

```bash
echo "env.JAVA_HOME = '$MAMBA_ROOT_PREFIX/envs/cellprofiler/lib/jvm'" > local.config
```

## Step 4. Test: dry run

A dry run starts all jobs, but the jobs make small fake files instead of running CellProfiler:

```bash
nextflow run . -profile test,local -c local.config -stub-run
```

It must show `6 image set(s), 6 file(s) -> 3 chunk(s)` and end without `ERROR`.

## Step 5. Test: real CellProfiler

```bash
nextflow run . -profile test,local -c local.config
```

The run took 27 seconds in our test. Check the tables:

```bash
python3 - <<'EOF'
import csv
f = "results_test/cellprofiler_tables/"
image = list(csv.DictReader(open(f + "Image.csv")))
nuclei = list(csv.DictReader(open(f + "Nuclei.csv")))
print("image sets:", len(image), "nuclei:", len(nuclei))
EOF
```

The output must be `image sets: 6 nuclei: 51`. If it is different, do not run your own images. Find the
cause first.

To test `-resume`, run the command of step 5 again with `-resume`. Nextflow then takes all 6 jobs from its
cache and runs none again.

## Step 6. Run your images

Use `-profile local -c local.config` and the options of [Run on your data](../usage.md). First do a dry run
to check your `--group_regex`:

```bash
nextflow run . -profile local -c local.config -stub-run \
    --illum_pipeline /path/to/1_illumination.cppipe \
    --pipeline /path/to/2_analysis_cellpose.cppipe \
    --input_dir /path/to/images \
    --outdir /path/to/results \
    --group_regex '^(.+?_s\d+)_x' \
    --total_cpus 8 --max_cpus 8 --max_memory 32.GB
```

The image folder needs one sub-folder per plate. Check the line `P plate(s): N image set(s), M file(s) -> K
chunk(s)` and the line of each plate. N must be the number of sites. Then run the same command without
`-stub-run`. If the run stops, run it again with `-resume`. A pipeline with RunCellpose needs Cellpose 3.1.1.2
in your conda environment, and `CELLPOSE_LOCAL_MODELS_PATH` set to a folder with the `nuclei` and `cyto3`
models; otherwise use the Cellpose image with Docker.

Set `--max_cpus` and `--max_memory` to less than the workstation has. Other people can share the server.
Each CellProfiler job asks for 1 core and 8 GB.

## Troubleshooting

| Message | Cause and solution |
| --- | --- |
| `cellprofiler: command not found`, or exit status 127 | Run the line of step 2. |
| `Could not import CellProfiler (No module named 'cellprofiler_core')` | The jobs use another Python, for example of an active virtual environment. Leave that environment (`deactivate`) and run the line of step 2 again, so that the `cellprofiler` environment comes first in `PATH`. |
| `Error finding javahome on linux: ['bash', '-c', 'type -p java']` | CellProfiler cannot find Java. Run the line of step 2, and use `-c local.config` (step 3). |
| `Cannot find Java or it's a wrong version` | Nextflow uses the wrong Java. Run the lines of [Installation, step 5](../getting-started/installation.md#step-5-activate-nextflow). |
| Many lines `WARNING:root:Multiple definitions of module` | These lines are harmless. The conda build of CellProfiler writes them for each job. |
| `Process requirement exceeds available memory` | Set `--max_memory` and `--max_cpus` to the size of your workstation. |
| Other errors | See [Troubleshooting](troubleshooting.md). |
