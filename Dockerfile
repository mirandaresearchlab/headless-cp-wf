# syntax=docker/dockerfile:1.7

ARG CELLPROFILER_VERSION=4.2.8
ARG CELLPROFILER_DIGEST=sha256:fec440caa2b44edf80f9bd440a3d8c6b214d72437332ad2586a32d79e2eae2a4
ARG NEXTFLOW_VERSION=26.04.6

FROM eclipse-temurin:21-jre-jammy AS java-runtime

FROM alpine:3.22 AS nextflow-download
ARG NEXTFLOW_VERSION
ARG NEXTFLOW_SHA256=182a63c74074e2dc7956ffa3c8cd59de952ed2c44394e21faf5e1736b945444c
RUN apk add --no-cache curl \
    && curl --fail --location --silent --show-error \
        "https://github.com/nextflow-io/nextflow/releases/download/v${NEXTFLOW_VERSION}/nextflow-${NEXTFLOW_VERSION}-dist" \
        --output /nextflow \
    && echo "${NEXTFLOW_SHA256}  /nextflow" | sha256sum -c - \
    && chmod 0755 /nextflow

FROM cellprofiler/cellprofiler:${CELLPROFILER_VERSION}@${CELLPROFILER_DIGEST}

ARG CELLPROFILER_VERSION
ARG NEXTFLOW_VERSION

LABEL org.opencontainers.image.title="cp-headless" \
      org.opencontainers.image.description="Nextflow and CellProfiler workflow for headless image analysis" \
      org.opencontainers.image.version="1.0.0"

# Keep CellProfiler's own Java configuration intact. Nextflow alone uses the
# Java 21 runtime selected through JAVA_CMD.
COPY --from=java-runtime /opt/java/openjdk /opt/nextflow-java
COPY --from=nextflow-download /nextflow /usr/local/bin/nextflow

ENV JAVA_CMD=/opt/nextflow-java/bin/java \
    NXF_ANSI_LOG=false

WORKDIR /opt/cp-headless
COPY main.nf nextflow.config README.md ./
COPY conf/ ./conf/
COPY --chmod=0755 bin/ ./bin/
COPY tests/ ./tests/
COPY --chmod=0755 scripts/docker-entrypoint.sh /usr/local/bin/cp-headless

# Any --user must read the workflow, whatever file modes the build checkout had.
RUN chmod -R a+rX /opt/cp-headless \
    && NXF_HOME=/tmp/nextflow-build nextflow -version \
    && cellprofiler --version

# User data and Nextflow's work directory should be mounted under /workspace.
WORKDIR /workspace

# The local profile is intentional: CellProfiler is already installed in this
# image, so the workflow does not need Docker-in-Docker or the host Docker socket.
ENTRYPOINT ["cp-headless"]
