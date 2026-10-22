# syntax=docker/dockerfile:1.7

# Task image for the CellProfiler jobs of cp-headless (PATCH_PIPELINE, ILLUM, CELLPROFILER) when the analysis
# pipeline segments with Cellpose (the RunCellpose plugin). It is the official CellProfiler 4.2.8 image plus:
#   - Cellpose 3.1.1.2 and CPU-only PyTorch 2.4.1, in CellProfiler's own Python (/opt/venv, Python 3.8),
#   - the pretrained Cellpose models nuclei and cyto3 in /opt/cellpose/models (CELLPOSE_LOCAL_MODELS_PATH):
#     compute nodes often have no internet, so no job may download a model,
#   - the plugins of cp-plugins/ (runcellpose.py, enforceobjectsonetoone.py) in /opt/cp-plugins.
# The workflow passes the plugins of the repository (--plugins_dir); the copy in the image is for use without
# the repository.
#
# Build from the repository root, for linux/amd64 (the Berzelius CPU nodes):
#   docker build --platform linux/amd64 -f containers/cellprofiler-cellpose/Dockerfile \
#       -t cp-headless-cellpose:1.0.0 .
# Then push it to a registry and pin it by digest in nextflow.config (see containers/README.md).

# The base image is pinned by its digest, so a re-pushed tag cannot change it (same as params.container).
ARG CELLPROFILER_DIGEST=sha256:fec440caa2b44edf80f9bd440a3d8c6b214d72437332ad2586a32d79e2eae2a4
FROM cellprofiler/cellprofiler:4.2.8@${CELLPROFILER_DIGEST}

LABEL org.opencontainers.image.title="cp-headless-cellpose" \
      org.opencontainers.image.description="CellProfiler 4.2.8 with Cellpose 3.1.1.2 (CPU), its models and plugins" \
      org.opencontainers.image.source="https://github.com/mirandaresearchlab/headless-cp-wf" \
      org.opencontainers.image.version="1.0.0"

# Cellpose and its dependencies, all pinned. --no-deps: pip installs exactly this list and changes no package of
# CellProfiler. pip check stops the build if a requirement is not met.
COPY containers/cellprofiler-cellpose/requirements.txt /tmp/cellpose-requirements.txt
RUN pip install --no-cache-dir --no-deps \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        -r /tmp/cellpose-requirements.txt \
    && pip check \
    && rm /tmp/cellpose-requirements.txt

# The models. Cellpose downloads a model on first use into CELLPOSE_LOCAL_MODELS_PATH; here that happens once,
# in the build. The checksums stop the build if a model file on cellpose.org changes.
# NUMBA_CACHE_DIR: Cellpose compiles functions with numba and caches them. The image is read-only under
# Apptainer, so the cache must go to a writable folder (the workflow sets it to the job folder).
ENV CELLPOSE_LOCAL_MODELS_PATH=/opt/cellpose/models \
    NUMBA_CACHE_DIR=/tmp/numba-cache
COPY containers/cellprofiler-cellpose/models.sha256 /opt/cellpose/models.sha256
RUN mkdir -p "$CELLPOSE_LOCAL_MODELS_PATH" \
    && python -c "from cellpose import models; models.Cellpose(model_type='nuclei'); models.Cellpose(model_type='cyto3')" \
    && cd "$CELLPOSE_LOCAL_MODELS_PATH" \
    && sha256sum * \
    && sha256sum -c /opt/cellpose/models.sha256 \
    && chmod -R a+rX /opt/cellpose

# The plugins, readable for any user (Apptainer runs as the calling user).
COPY cp-plugins/ /opt/cp-plugins/
RUN chmod -R a+rX /opt/cp-plugins

# Smoke test: CellProfiler starts, and Cellpose and PyTorch import (CPU build).
RUN cellprofiler --version \
    && python -c "import cellpose, torch; import importlib.metadata as m; print('cellpose', m.version('cellpose'), 'torch', torch.__version__); assert not torch.cuda.is_available()"
