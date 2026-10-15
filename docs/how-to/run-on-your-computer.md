# Run on your own computer

This guide tells you how to run the workflow on your own computer, from `git clone` to a run on your images.
Use it on a Mac or a Linux computer with Docker Desktop or Docker Engine. For a shared Linux server without
root rights, use [Run with rootless Docker](run-with-rootless-docker.md). For a cluster, use
[Run on a Slurm cluster](run-on-hpc.md) or [Run on Berzelius](run-on-berzelius.md).

!!! note "Testing status"
    The steps of this guide ran on a Mac with Apple Silicon (Docker Desktop, Java 21), from a new clone of the
    repository. They ended with 6 image sets and 51 nuclei. We did not run them on Windows, on an Intel Mac or
    on a Linux desktop. On Windows, use Linux inside WSL 2. Tell us if a step does not work.

## What you need

| Need | How to check | If it is missing |
| --- | --- | --- |
| Git | `git --version` | macOS: `xcode-select --install`. Linux: `sudo apt install git`. |
| Java 17 to 26. Java 27 and newer do **not** work. | `java -version` | macOS: `brew install openjdk@21`. Ubuntu: `sudo apt install openjdk-21-jre-headless`. |
| Docker, and it runs | `docker info` shows no error | Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Mac) or Docker Engine (Linux), and start it. |
| [uv](https://docs.astral.sh/uv/) (installs Nextflow for you) | `uv --version` | macOS: `brew install uv`. Others: see the uv page. |
| Space for the CellProfiler image | `df -h .` | A few GB, plus about 2 times the size of your images. |

The CellProfiler 4.2.8 image exists only for Linux on amd64. On a Mac with Apple Silicon, Docker Desktop runs it
with emulation. This works, but it is slower.

## Step 1. Get the code

```bash
git clone https://github.com/mirandaresearchlab/headless-cp-wf.git
cd headless-cp-wf
./scripts/bootstrap.sh
source .venv/bin/activate
```

`bootstrap.sh` makes the folder `.venv` and installs Nextflow into it. It also installs a Git hook for people
who change the code. Run `source .venv/bin/activate` again in each new terminal, before you use `nextflow`.
The other guides tell you to come back to [Installation](../getting-started/installation.md) if you skip this step.

!!! tip "No uv?"
    You can also install Nextflow yourself. See [Installation](../getting-started/installation.md).

## Step 2. Select a supported Java

Nextflow refuses Java 27 and newer, and Homebrew installs the newest Java. Run `nextflow -version`. If it
prints `Cannot find Java or it's a wrong version`, follow
[Select a supported Java](../getting-started/installation.md#select-a-supported-java) in the installation guide,
and then come back here.

## Step 3. Test: do a dry run

A dry run (a *stub run*) starts every job of the workflow, but the jobs make small fake files instead of
running CellProfiler. It needs no Docker and takes a few seconds. It shows that Nextflow works and that the
steps connect:

```bash
bash scripts/test-nextflow.sh
```

The script finds a supported Java itself and deletes its files at the end. The output ends with:

```text
[SUCCESS] completed=5 failed=0 cached=0
```

## Step 4. Test: run real CellProfiler

```bash
nextflow run . -profile test,docker
```

The first run downloads the CellProfiler image, which takes some minutes. The run itself takes a few
minutes on a Mac with Apple Silicon, and about 10 seconds on Linux with amd64. The output ends with:

```text
[SUCCESS] completed=5 failed=0 cached=0
```

The tables are in `results_test/features/`. The test is correct if `MyExpt_Image.csv` has 6 rows (image sets)
and `MyExpt_Nuclei.csv` has 51 rows (nuclei):

```bash
python3 -c "
import csv
print('image sets:', len(list(csv.DictReader(open('results_test/features/MyExpt_Image.csv')))))
print('nuclei:    ', len(list(csv.DictReader(open('results_test/features/MyExpt_Nuclei.csv')))))
"
```

The [tutorial](../tutorials/first-run.md) shows all result files and explains them.

## Step 5. Run your images

First do a dry run on your folder. It checks the file names, your `--group_regex` and your parameters in
seconds, and it does not start CellProfiler:

```bash
nextflow run . -profile local -stub-run \
    --pipeline /path/to/analysis.cppipe \
    --input_dir /path/to/images \
    --outdir /path/to/results_stub \
    --group_regex '^(.+?_s\d+)_w\d' \
    --max_cpus 4 --max_memory 12.GB
```

Look at the line `[cp-headless] N image set(s), M file(s) -> K chunk(s)`. Check that N is the number of sites
that you expect. If not, see [Prepare your image folder](format-image-folder.md).

Then run the same command with real CellProfiler: replace `-profile local -stub-run` with `-profile docker`
and use your real `--outdir`:

```bash
nextflow run . -profile docker \
    --pipeline /path/to/analysis.cppipe \
    --input_dir /path/to/images \
    --outdir /path/to/results \
    --group_regex '^(.+?_s\d+)_w\d' \
    --max_cpus 4 --max_memory 12.GB
```

Set `--max_cpus` and `--max_memory` to **less than your computer has**. Each CellProfiler job asks for 8 GB
of memory. The workflow stops a job that asks for more than `--max_memory`.

!!! warning "Docker Desktop has its own memory limit"
    Docker Desktop runs in a virtual machine with its own limit, often 8 GB. A job that needs more stops
    with exit code 137. Open Docker Desktop, go to *Settings > Resources*, raise *Memory*, and apply.

To continue a run that stopped, give the same command again with `-resume`. See [Run on your
data](../usage.md) for all options, and [Output](../output.md) for the result files.

## Troubleshooting

| Problem | Cause and solution |
| --- | --- |
| `nextflow: command not found` | Run `source .venv/bin/activate` in the repository folder. |
| `Cannot find Java or it's a wrong version` | Your Java is too new or missing. See step 2. |
| `Cannot connect to the Docker daemon` | Docker Desktop is not running. Start it and wait until it shows "running". |
| `Process requirement exceeds available memory` | Set `--max_memory` and `--max_cpus` to less than your computer has (step 5). |
| Jobs stop with exit code 137 | Not enough memory. Raise the memory of Docker Desktop (step 5). |
| `no space left on device` | Docker has no free space. Run `docker system df`, and remove old images with `docker image prune`. |
| Other errors | See [Troubleshooting](troubleshooting.md). |
