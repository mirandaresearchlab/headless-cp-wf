# Installation

This page tells you how to install the workflow on a lab workstation. A lab workstation is an Ubuntu Linux
system where you are `root`, for example the container that you reach with SSH on a lab server. After this
page, you choose how CellProfiler runs: without Docker or with Docker.

For Berzelius, do not use this page. Use [Berzelius: set up](../how-to/berzelius-setup.md).

!!! note "Testing status"
    We ran every command of this page as `root` in a clean Ubuntu 24.04 container (amd64) on 2026-10-15.
    We did not run them on a lab server.

## Choose how CellProfiler runs

| Way | Use it when | Guide |
| --- | --- | --- |
| Without Docker | Your workstation has no Docker. This is the simplest way on a lab workstation. | [Run without Docker](../how-to/run-without-docker.md) |
| With Docker | Docker works in your workstation. CellProfiler then runs in the official container. | [Run with Docker](../how-to/run-with-docker.md) |

Both ways gave the same results on the test data. See the guides for the details.

## What you need

| Need | How to check |
| --- | --- |
| Ubuntu Linux on amd64 | `uname -m` shows `x86_64`. CellProfiler 4.2.8 exists only for Linux on amd64. |
| A terminal as `root` | `whoami` shows `root`. If you are not `root`, put `sudo` before each `apt` command. |
| Internet access | The installation downloads packages. |
| About 5 GB of free space | `df -h ~` |

## Step 1. Install the system tools

```bash
apt update
apt install -y git procps curl ca-certificates bzip2 python3
```

Run `apt update` first. Without it, `apt install` can fail with `Unable to locate package`. A minimal
container often lacks these programs. Nextflow needs `ps` from the package `procps`. The merge step of the
workflow needs `python3` when it runs without a container, for example in the dry run of step 6.

## Step 2. Get the code

```bash
git clone https://github.com/mirandaresearchlab/headless-cp-wf.git
cd headless-cp-wf
```

## Step 3. Install micromamba

micromamba installs Nextflow, Java and (for the way without Docker) CellProfiler in separate environments.
Run the installer, and press Enter at each question to accept the default:

```bash
bash <(curl -L https://micro.mamba.pm/install.sh)
```

The installer puts the program in `~/.local/bin/micromamba`. Your terminal does not know the new command
yet. Run these two lines:

```bash
export PATH="$HOME/.local/bin:$PATH"
export MAMBA_ROOT_PREFIX="$HOME/micromamba"
micromamba --version
```

The last command prints a version number, for example `2.9.0`.

## Step 4. Install Nextflow and Java

```bash
micromamba create -y -n nextflow -c conda-forge -c bioconda nextflow=26.04.6 openjdk=21
```

Nextflow needs Java 17 to 26. This environment has Java 21.

## Step 5. Activate Nextflow

Run these lines in each new terminal, before you use `nextflow`:

```bash
export MAMBA_ROOT_PREFIX="$HOME/micromamba"
export PATH="$MAMBA_ROOT_PREFIX/envs/nextflow/bin:$HOME/.local/bin:$PATH"
export JAVA_HOME="$MAMBA_ROOT_PREFIX/envs/nextflow/lib/jvm"
unset JAVA_CMD
```

`JAVA_HOME` makes Nextflow use the Java 21 of the environment, even if the system has another Java.
To keep these lines, add them to the end of `~/.bashrc`. A new terminal then runs them for you.

## Step 6. Check the installation

```bash
nextflow -version
nextflow run . -profile test,local -stub-run
```

The first command shows `version 26.04.6`. The second command is a dry run on the test data. Its jobs make
small fake files instead of running CellProfiler, so it needs no CellProfiler and no Docker. It must show:

```text
[cp-headless] 6 image set(s), 6 file(s) -> 3 chunk(s)
```

It must end without `ERROR`. Then go on with [Run without Docker](../how-to/run-without-docker.md) or
[Run with Docker](../how-to/run-with-docker.md).

## Troubleshooting

| Message | Cause and solution |
| --- | --- |
| `Unable to locate package` | Run `apt update`, then the `apt install` command again. |
| `micromamba: command not found` | Your terminal does not know the new program. Run the two `export` lines of step 3. |
| `nextflow: command not found` | Run the lines of step 5. |
| `Cannot find Java or it's a wrong version` | Nextflow uses another Java. Run the lines of step 5, including `unset JAVA_CMD`. |
| `Command 'ps' required by nextflow ... cannot be found` | Install `procps` (step 1). |
| `MERGE_FEATURES` fails in the dry run with `python3: not found` or exit status 127 | Install `python3` (step 1). |

To change the code of the workflow, see [Contributing](../about/contributing.md). It uses a separate
development environment.
