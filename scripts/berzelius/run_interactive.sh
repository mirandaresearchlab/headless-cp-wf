#!/usr/bin/env bash

# Run cp-headless on your own data inside an interactive job on a Berzelius CPU node.
# All CellProfiler jobs run on this node (local executor). Nextflow submits no Slurm jobs, so there is
# no job inside a job. For long runs, use submit.sh: it gives each chunk its own Slurm job.
#
#   interactive -A <account> -p berzelius-cpu -n 1 -c 16 -t 04:00:00
#   bash scripts/berzelius/run_interactive.sh ENV_FILE PARAMS_FILE RUN_DIR [-- NEXTFLOW_ARGS]
#
# The guide is docs/how-to/run-on-berzelius.md. To continue a stopped run, run the same command again.
set -euo pipefail

usage() {
    echo "Usage: $0 ENV_FILE PARAMS_FILE RUN_DIR [-- NEXTFLOW_ARGS]   (RUN_DIR: a folder in /proj)" >&2
}

# Stop with a message. Exit code 2 = wrong settings (Nextflow did not start).
fail() {
    echo "ERROR: $*" >&2
    exit 2
}

# Three arguments. Everything after "--" goes unchanged to `nextflow run`.
[[ $# -ge 3 ]] || {
    usage
    exit 2
}
env_file="$1" params="$2" run_dir="$3"
shift 3
[[ "${1:-}" == "--" ]] && shift
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Only inside a Slurm job, and only on a CPU partition. Login nodes are not for computing, and GPU nodes
# would charge GPU hours.
if [[ -z "${SLURM_JOB_ID:-}" ]]; then
    fail "run this inside an interactive job on a CPU node, not on a login node:
  interactive -A <account> -p berzelius-cpu -n 1 -c 16 -t 04:00:00"
fi
case "${SLURM_JOB_PARTITION:-}" in
    berzelius-cpu | berzelius-hopper-cpu) ;;
    *) fail "this job runs in partition '${SLURM_JOB_PARTITION:-unknown}'. Use berzelius-cpu or berzelius-hopper-cpu." ;;
esac

# The files must exist. The run folder holds the -resume cache, so it must not be in $HOME (20 GB).
[[ -f "$env_file" ]] || fail "settings file not found: $env_file"
[[ -f "$params" ]] || fail "params file not found: $params"
[[ "$run_dir" == /* ]] || fail "RUN_DIR must be an absolute path in /proj, not '$run_dir'"
case "$run_dir/" in
    "$HOME"/*) fail "RUN_DIR $run_dir is in your home directory (20 GB, 1 million files). Use /proj/<project>/users/\$USER/..." ;;
esac

# Load Nextflow, Java and the cache folders from the settings file (made by make_env.sh).
# shellcheck source=/dev/null
source "$env_file"
: "${NXF_APPTAINER_CACHEDIR:?$env_file must set NXF_APPTAINER_CACHEDIR}"
mkdir -p "$run_dir" "$NXF_APPTAINER_CACHEDIR"
params="$(cd "$(dirname "$params")" && pwd)/$(basename "$params")"
cd "$run_dir"

# Use only the cores of this job (--total_cpus: all plates together). Berzelius gives about 7.7 GB of memory
# per core: use 7 GB per core.
cpus="${SLURM_CPUS_ON_NODE:-${SLURM_CPUS_PER_TASK:-1}}"
memory_gb=$((cpus * 7))
cat >interactive.config <<EOF
// Made by run_interactive.sh: the jobs run on this node, inside the interactive job $SLURM_JOB_ID.
process.executor = 'local'
process.scratch  = false
executor.cpus    = $cpus
executor.memory  = '$memory_gb GB'
EOF

echo "Interactive run in job $SLURM_JOB_ID on $(hostname): $cpus cores, $memory_gb GB, run folder $run_dir"
nextflow run "$repo" \
    -profile berzelius \
    -c interactive.config \
    -params-file "$params" \
    -work-dir "$run_dir/work" \
    -ansi-log false \
    -resume \
    --slurm_account "${SLURM_JOB_ACCOUNT:?}" \
    --slurm_partition "$SLURM_JOB_PARTITION" \
    --container_cache "$NXF_APPTAINER_CACHEDIR" \
    --max_cpus "$cpus" \
    --max_memory "$memory_gb.GB" \
    --total_cpus "$cpus" \
    --total_memory "$memory_gb.GB" \
    "$@"
