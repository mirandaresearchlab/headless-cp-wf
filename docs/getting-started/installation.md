# Install the workflow

This page prepares a shell that can run Nextflow and CellProfiler.

## Before you start

Use a Linux workstation or your cluster's supported Linux environment.
The repository uses Bash and Unix commands. Other operating systems were not validated here.
Obtain a copy of this repository from your maintainer, then open a terminal in its root folder.
The root contains `main.nf` and `environment.yml`.

Install Conda using your institution's instructions or the
[official Miniforge guide](https://github.com/conda-forge/miniforge#install).
Provide Java 17 or 21 for the Nextflow launcher.
Nextflow requires Bash and Java as described in its [installation guide](https://docs.seqera.io/nextflow/install).

Installation commands below are setup recipes. They were not executed here because Conda and Nextflow were unavailable.

## 1. Create the CellProfiler environment

```bash
conda env create -f environment.yml
conda activate cp-headless
```

Expected result: Conda creates and activates `cp-headless`.
The environment pins Python 3.9.19 and CellProfiler 4.2.8.1.
It also includes NumPy, SciPy, scikit-image, tifffile, pandas, and pytest.
The file pins key packages, but it is not a complete dependency lock file.
Allow time and internet access for downloads and dependency resolution.

!!! important "Activate this environment for each run"
    The profiles enable Conda support but no process declares a Conda environment.
    Nextflow therefore uses the Python and CellProfiler commands from the launch environment.
    The profiles do not automatically install `environment.yml`.

## 2. Install Nextflow separately

Keep Nextflow available outside the CellProfiler environment.
Follow the [official installation guide](https://docs.seqera.io/nextflow/install) to install version 25.10.4 or later.
Use 25.10.4 when reproducing the baseline documented in this repository.

If activating Conda changes Java, set `NXF_JAVA_HOME` to your Nextflow-compatible Java installation.
Do not change CellProfiler's Java dependencies merely to satisfy the Nextflow launcher.
Your cluster administrator can provide the appropriate Java location.

## 3. Check the active tools

Run these checks after activating `cp-headless`:

```bash
python --version
python -c "from importlib.metadata import version; print(version('cellprofiler')); print(version('cellprofiler-core'))"
nextflow -version
cellprofiler --help
```

Expected values: Python 3.9.19, two lines containing 4.2.8.1, Nextflow 25.10.4 or later, and CellProfiler help text.
An import error or missing command means the environment is not ready.

## 4. Prepare storage and data

Keep inputs, results, and work files in separate folders.
The default local budget is 2 CPUs and 16 GB. Each task requests 6 GB.
These are scheduler requests, not measured minimum requirements for all datasets.
See [resource planning](../reference/resources.md) before processing large images.

The repository does not include images. Use your own images, with one folder per plate.
Then continue with the [first run](../tutorials/first-run.md).
