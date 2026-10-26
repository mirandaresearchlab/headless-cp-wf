#!/usr/bin/env bash
# Run the workflow inside a Berzelius interactive CPU session, with the local executor.
# Use it to test. Nextflow shares the session's cores between tasks: one core and one
# CellProfiler process per batch, so N cores run N batches at the same time.
# No extra Slurm jobs are submitted.
#
# Start a session first (on the login node), for example 18 cores for 1 hour:
#   interactive -A <account> -p berzelius-cpu -n 1 -c 18 -t 01:00:00
# Then, inside the session, from the repository folder:
#   bash scripts/berzelius-interactive.sh <images> <project> [batch_size] [extra Nextflow options]
#
# images      folder with one sub-folder per plate
# project     output name under $PROJ/runs/projects/
# batch_size  image sets per CellProfiler task (default 1: every image set gets its own core)
# PROJ and CP_ENV can be set in the environment to override the defaults below.
# The conda environment must exist first: see docs/how-to/run-on-hpc.md, "Set up once".
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -z "${SLURM_JOB_ID:-}" ]]; then
    echo "Not in a Slurm job. Start an interactive session first (see the top of this script)." >&2
    exit 1
fi
if [[ $# -lt 2 ]]; then
    echo "Usage: bash scripts/berzelius-interactive.sh <images> <project> [batch_size] [options]" >&2
    exit 1
fi

images="$(realpath "$1")"
project="$2"
batch_size="${3:-1}"
PROJ="${PROJ:-/proj/berzelius-2025-380/users/$USER}"
CP_ENV="${CP_ENV:-$PROJ/envs/cp-headless}"

# A CPU node has about 7.7 GB per core; keep 0.7 GB per core free for Nextflow and the OS.
cores="${SLURM_CPUS_PER_TASK:-$(nproc)}"
total_memory="$((cores * 7)) GB"

module load Miniforge3/25.3.1-0
eval "$(conda shell.bash hook)"
conda activate "$CP_ENV"
export NXF_HOME="$PROJ/.nextflow"

echo "Job $SLURM_JOB_ID: $cores cores, $total_memory, images $images, batch_size $batch_size, project $project"

nextflow run . -profile local -resume \
    --images "$images" \
    --configs "$PWD/cp-configs" \
    --outdir "$PROJ/runs" --project "$project" \
    --nf_work_dir "$PROJ/runs/$project-work" \
    --batch_size "$batch_size" \
    --total_cpus "$cores" --total_memory "$total_memory" \
    --task_cpus 1 --task_memory '7 GB' --task_time '2h' \
    "${@:4}"
