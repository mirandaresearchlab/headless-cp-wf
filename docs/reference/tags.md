# Container images

This page lists the container images of the workflow. How to use them: [Run with Docker](../how-to/run-with-docker.md).

| Image | Digest | Contents | Used by |
| --- | --- | --- | --- |
| `cellprofiler/cellprofiler:4.2.8` (Docker Hub, official) | `sha256:fec440caa2b44edf80f9bd440a3d8c6b214d72437332ad2586a32d79e2eae2a4` | CellProfiler 4.2.8, Python 3.8, Java 11, Ubuntu 18.04. Linux on amd64 only. | Each job of the `docker`, `apptainer`, `singularity`, `slurm` and `berzelius` profiles (`--container`) |
| `cp-headless:1.0.0` (build it yourself) | — | The image above, plus Nextflow 26.04.6, Java 21 and the workflow | The all-in-one use, see [Run with Docker](../how-to/run-with-docker.md#the-all-in-one-image-optional) |

Without Docker, the `local` profile uses CellProfiler from the conda package `cellprofiler=4.2.8` (bioconda),
not an image. It has newer libraries than the official image. See
[Run without Docker](../how-to/run-without-docker.md#how-it-differs-from-the-container).

**Why a digest.** The workflow pins the CellProfiler image by its digest, not only by its tag. Somebody can
push a new image under the same tag, but not under the same digest. Thus each run uses exactly the same
software. `pipeline_info/run_info.json` records the image of each run.

**Another CellProfiler version.** Set `--container` to another image, for example a newer CellProfiler. Then
check its Python version: the scripts in `bin/` must work on it. See
[Contributing](../about/contributing.md#update-the-cellprofiler-version).
