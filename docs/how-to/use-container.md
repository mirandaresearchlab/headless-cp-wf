# Use the containers

This guide tells you how to use the two container images of the workflow. [Container images](../reference/tags.md)
lists the images.

!!! info "Before you start"
    This guide assumes that you cloned the repository, installed the tools and activated the environment.
    If you did not, do [Installation](../getting-started/installation.md) first. To check, open a terminal in the folder `headless-cp-wf`
    and run `source .venv/bin/activate` and then `nextflow -version`. It must print a version number.

## The CellProfiler image (one container per job)

With `-profile docker`, `apptainer` or `singularity`, Nextflow runs on your computer and starts the
CellProfiler image `cellprofiler/cellprofiler:4.2.8` for each job. You do not start the image yourself.

```bash
nextflow run . -profile test,docker
```

The `docker` profile removes the entry point of the image (`--entrypoint ""`). It also runs the jobs as your
user, so that your results do not belong to root.

To look inside the image, for example to check its CellProfiler version:

```bash
docker run --rm --platform linux/amd64 --entrypoint "" cellprofiler/cellprofiler:4.2.8 cellprofiler --version
```

```text
4.2.8
```

With Apptainer, Nextflow downloads the image once into `--container_cache` and converts it to a `.sif` file.

## The all-in-one image (Nextflow inside the container)

This image holds Nextflow, Java 21, CellProfiler 4.2.8 and the workflow. Inside the image, the workflow uses
the `local` profile. Thus it needs no access to the Docker service of your computer. Use it when you cannot
install Nextflow on your computer.

**Build it once**, in the folder of the repository:

```bash
docker build --platform linux/amd64 -t cp-headless:1.0.0 .
```

**Run it.** The current folder becomes the work area `/workspace`:

```bash
docker run --rm --platform linux/amd64 \
    --user "$(id -u):$(id -g)" \
    -v "$PWD:/workspace" \
    cp-headless:1.0.0 \
    --pipeline /workspace/analysis.cppipe \
    --input_dir /workspace/images \
    --outdir /workspace/results \
    --group_regex '^(.+_s\d+)_(?:DNA|Actin)\.tif$' \
    --chunk_size 50 \
    --max_cpus 8 \
    --max_memory 32.GB
```

- The work area keeps `work/`, `.nextflow/` and the results. Thus `-resume` also works with this image.
- For images in another folder, add a read-only mount, for example `-v /path/to/data:/data:ro`, and use
  paths in `/data`.
- On Windows, remove the `--user` line.
- `docker run --rm cp-headless:1.0.0 --help` shows a short help text.

The image runs the included test data like this:

```bash
docker run --rm --platform linux/amd64 --user "$(id -u):$(id -g)" -v "$PWD:/workspace" cp-headless:1.0.0 \
    --pipeline /opt/cp-headless/tests/test.cppipe --input_dir /opt/cp-headless/tests/images \
    --outdir /workspace/results --group_regex '^(.+)$' --chunk_size 2 --max_cpus 2 --max_memory 3.GB
```

### Test the all-in-one image

Do these tests before you use your data. The first test shows that the image starts. The second runs the
included test data with the stub jobs (no CellProfiler). The third runs CellProfiler:

```bash
docker run --rm --platform linux/amd64 cp-headless:1.0.0 --help
docker run --rm --platform linux/amd64 --user "$(id -u):$(id -g)" -v "$PWD:/workspace" cp-headless:1.0.0 -stub-run \
    --pipeline /opt/cp-headless/tests/test.cppipe --input_dir /opt/cp-headless/tests/images \
    --outdir /workspace/results_stub --group_regex '^(.+)$' --chunk_size 2 --max_cpus 2 --max_memory 3.GB
```

The second command must end with the line `Submitted process > MERGE_FEATURES`, and `results_stub/features/`
must have the tables. (This image does not print the `[SUCCESS]` line.) Run the command from the
section above ("The image runs the included test data like this") without `-stub-run` for the third test.
It must give 6 image sets and 51 nuclei in `results/features/`.

!!! note "Apple Silicon"
    The CellProfiler 4.2.8 image exists only for Linux on amd64. Docker Desktop emulates it with
    `--platform linux/amd64`. This works, but it is slower.
