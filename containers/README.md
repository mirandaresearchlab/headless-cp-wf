# Container images of the workflow

| Image | Folder | Used by | Contents |
| --- | --- | --- | --- |
| Cellpose image | `cellprofiler-cellpose/` | PATCH_PIPELINE, ILLUM, CELLPROFILER (`--container`) | CellProfiler 4.2.8 (official image), Cellpose 3.1.1.2, CPU PyTorch 2.4.1, the Cellpose models `nuclei` and `cyto3`, the plugins of `cp-plugins/` |
| (root) `Dockerfile` | `../Dockerfile` | not used by the jobs | Nextflow + CellProfiler in one image, to run the whole workflow on a workstation |

The Cellpose image is pinned: every package has a fixed version, and the base image has a fixed digest. A
pipeline without Cellpose can use the official CellProfiler image (the default of `--container`). A pipeline
with RunCellpose needs the Cellpose image: the workflow stops if the official image is set.

## Build

Run the command from the repository root (the image copies `cp-plugins/` and the requirement file).

```bash
# linux/amd64 only (the Berzelius CPU nodes). About 2 GB of new layers.
docker build --platform linux/amd64 -f containers/cellprofiler-cellpose/Dockerfile \
    -t cp-headless-cellpose:1.0.0 .
```

The build checks itself: `pip check` must pass, the Cellpose model files must have the checksums of
`cellprofiler-cellpose/models.sha256`, and CellProfiler, Cellpose and PyTorch must import.

## Check the image

```bash
# Cellpose on CPU, the models in the image, no network.
docker run --rm --platform linux/amd64 --network none --entrypoint "" cp-headless-cellpose:1.0.0 \
    python -c "from cellpose import models; models.Cellpose(model_type='cyto3'); print('ok')"
```

## Publish and pin

The jobs on Berzelius pull the image with Apptainer, so the image must be in a registry, and the workflow
must name it by digest:

1. Push the image to a registry that Berzelius can reach, for example the GitHub Container Registry of the
   organisation:

   ```bash
   docker tag cp-headless-cellpose:1.0.0 ghcr.io/<org>/cp-headless-cellpose:1.0.0
   docker push ghcr.io/<org>/cp-headless-cellpose:1.0.0
   ```

2. Read the digest: `docker buildx imagetools inspect ghcr.io/<org>/cp-headless-cellpose:1.0.0`.
3. In `nextflow.config`, set `container` to `ghcr.io/<org>/cp-headless-cellpose@sha256:<digest>` (no tag:
   Apptainer can not pull a reference with both a tag and a digest). Update `nextflow_schema.json` (the test
   `tests/test_schema.py` checks that both agree).
4. On Berzelius, pull it once into `--container_cache` (see docs/how-to/berzelius-setup.md).

Never push a changed image under a tag that a run already used: make a new tag.
