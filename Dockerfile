# syntax=docker/dockerfile:1.7

# All-in-one image: Nextflow, Java 21, CellProfiler 4.2.8 and the workflow in one container.
# Build: docker build --platform linux/amd64 -t cp-headless:1.0.0 .
# Run:   docker run --rm cp-headless:1.0.0 --help
# The build has three stages: two small stages fetch Java and Nextflow, and the last stage adds them
# to the official CellProfiler image.

# Versions. The CellProfiler image is pinned by its digest, so a re-pushed tag cannot change it.
ARG CELLPROFILER_VERSION=4.2.8
ARG CELLPROFILER_DIGEST=sha256:fec440caa2b44edf80f9bd440a3d8c6b214d72437332ad2586a32d79e2eae2a4
ARG NEXTFLOW_VERSION=26.04.6

# Stage 1: a Java 21 runtime for Nextflow. (CellProfiler uses its own Java 11 and keeps it.)
FROM eclipse-temurin:21-jre-jammy AS java-runtime

# Stage 2: download Nextflow and stop the build if its checksum is wrong.
FROM alpine:3.22 AS nextflow-download
ARG NEXTFLOW_VERSION
ARG NEXTFLOW_SHA256=182a63c74074e2dc7956ffa3c8cd59de952ed2c44394e21faf5e1736b945444c
RUN apk add --no-cache curl \
    && curl --fail --location --silent --show-error \
        "https://github.com/nextflow-io/nextflow/releases/download/v${NEXTFLOW_VERSION}/nextflow-${NEXTFLOW_VERSION}-dist" \
        --output /nextflow \
    && echo "${NEXTFLOW_SHA256}  /nextflow" | sha256sum -c - \
    && chmod 0755 /nextflow

# Stage 3: the final image, based on the official CellProfiler image.
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

# The workflow files, and the start command (scripts/docker-entrypoint.sh) as "cp-headless".
WORKDIR /opt/cp-headless
COPY main.nf nextflow.config README.md ./
COPY conf/ ./conf/
COPY cp-plugins/ ./cp-plugins/
COPY --chmod=0755 bin/ ./bin/
COPY tests/ ./tests/
COPY --chmod=0755 scripts/docker-entrypoint.sh /usr/local/bin/cp-headless

# Any --user must read the workflow, whatever file modes the build checkout had.
# The two version commands check that Nextflow and CellProfiler start in the image.
RUN chmod -R a+rX /opt/cp-headless \
    && NXF_HOME=/tmp/nextflow-build nextflow -version \
    && cellprofiler --version

# User data and Nextflow's work directory should be mounted under /workspace.
WORKDIR /workspace

# The local profile is intentional: CellProfiler is already installed in this
# image, so the workflow does not need Docker-in-Docker or the host Docker socket.
ENTRYPOINT ["cp-headless"]
