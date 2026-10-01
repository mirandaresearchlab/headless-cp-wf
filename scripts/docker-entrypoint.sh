#!/usr/bin/env bash
set -euo pipefail

# The image supports arbitrary numeric --user values. Give each runtime user a
# writable Nextflow home without relying on /root or a named account.
export NXF_HOME="${NXF_HOME:-/tmp/nextflow-home-${UID}}"
mkdir -p "$NXF_HOME"

if [[ $# -eq 0 || "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    cat <<'EOF'
cp-headless container

Mount your data and a writable workspace, then pass normal Nextflow pipeline parameters:

  docker run --rm \
    -v "$PWD:/workspace" \
    cp-headless:1.0.0 \
    --pipeline /workspace/analysis.cppipe \
    --input_dir /workspace/images \
    --outdir /workspace/results

Additional arguments such as --chunk_size, --group_regex, and -resume are passed
directly to `nextflow run`. CellProfiler runs locally inside this container.
EOF
    exit 0
fi

exec nextflow run /opt/cp-headless -profile local "$@"
