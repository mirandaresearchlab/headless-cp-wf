# Installation

This page tells you what software the workflow needs, how to install it, and how to check the installation.

## Requirements

| Software | Version | Use |
| --- | --- | --- |
| [Nextflow](https://www.nextflow.io/) | 24.04 or newer (tested with 26.04.6) | Runs the workflow |
| Java | 17 to 26 | Nextflow needs it. Nextflow refuses Java 27 and newer. |
| [Docker](https://www.docker.com/) | any recent version | Runs CellProfiler on a laptop or workstation |
| [Apptainer](https://apptainer.org/) or Singularity | any recent version | Runs CellProfiler on a cluster |
| Disk space | a few GB, plus about 2× the size of your images | The CellProfiler image, the `work/` folder and the results |

You do not install CellProfiler yourself. The workflow uses the CellProfiler 4.2.8 container
`cellprofiler/cellprofiler:4.2.8`, pinned by its digest. This image exists only for Linux on amd64. On
Apple Silicon, Docker Desktop emulates it, which is slower.

## Install

=== "Development environment (recommended)"

    This installs Nextflow and the development tools in `.venv` with [uv](https://docs.astral.sh/uv/).

    ```bash
    git clone https://github.com/mirandaresearchlab/headless-cp-wf.git
    cd headless-cp-wf
    ./scripts/bootstrap.sh
    source .venv/bin/activate
    ```

=== "Nextflow only"

    Install Nextflow as its documentation describes, then get the workflow:

    ```bash
    curl -s https://get.nextflow.io | bash
    git clone https://github.com/mirandaresearchlab/headless-cp-wf.git
    cd headless-cp-wf
    ```

!!! warning "Java version"
    If `nextflow -version` shows `Cannot find Java or it's a wrong version`, select a supported Java.
    On macOS with Homebrew, for example: `export JAVA_HOME=/opt/homebrew/opt/openjdk@21`.

## Check the installation

Run the workflow once without CellProfiler. The jobs make small fake files instead (`-stub-run`), so this
takes a few seconds and needs no container:

```bash
bash scripts/test-nextflow.sh
```

The script finds Nextflow and a supported Java itself. The end of its output is:

```text
[cp-headless] 6 image set(s), 6 file(s) -> 3 chunk(s)
...
Submitted process > MERGE_FEATURES
```

Then do the [tutorial](../tutorials/first-run.md), which runs real CellProfiler.
