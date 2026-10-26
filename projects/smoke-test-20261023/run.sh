#!/usr/bin/env bash
set -euo pipefail
repo_dir=/root/projects/headless-cellprofiler
run_dir="$repo_dir/projects/smoke-test-20261023"
export NXF_VER=25.10.4
export NXF_JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
export NXF_SYNTAX_PARSER=v2
export PATH="/tmp/cp-headless-runtime/bin:/tmp/cp-nextflow-tools:$PATH"
cd "$run_dir/launch"
/tmp/cp-micromamba/bin/micromamba run -p /tmp/cp-headless-runtime nextflow run "$repo_dir/main.nf" -profile local \
  --images "$run_dir/images" --configs "$repo_dir/cp-configs" \
  --outdir "$run_dir/results" --project smoke \
  --nf_work_dir "$run_dir/work" --batch_size 1 \
  --total_cpus 2 --total_memory '16 GB' "$@"
