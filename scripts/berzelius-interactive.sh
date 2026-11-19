#!/usr/bin/env bash
# Run the workflow inside a Berzelius interactive CPU session, with the local executor.
# Use it to test. Nextflow shares the session's cores between tasks: one core and one
# CellProfiler process per batch, so N cores run N batches at the same time.
# No extra Slurm jobs are submitted.
#
# Start a session first (on the login node), for example 18 cores for 1 hour:
#   interactive -A <account> -p berzelius-cpu -n 1 -c 18 -t 01:00:00
# Then, inside the session, from the repository folder:
#   bash scripts/berzelius-interactive.sh <samplesheet.csv> <project> [batch_size] [extra Nextflow options]
#
# samplesheet  CSV file with one row per image file (see docs/reference/file-formats.md).
#              To make one from a folder of plate folders: python bin/make_samplesheet.py --help
# project     output name under $PROJ/runs/projects/
# batch_size  image sets per CellProfiler task (default 1: every image set gets its own core)
# PROJ, CP_ENV and CONFIGS (the folder with the two .cppipe files, default cp-configs) can be set
# in the environment to override the defaults below. For Cellpose-SAM on the CPU, for example:
#   CONFIGS=$PWD/cp-configs-cellpose bash scripts/berzelius-interactive.sh <samplesheet.csv> <project> 1 --segmentation cpu
# The conda environment must exist first: see docs/how-to/run-on-hpc.md, "Set up once".
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -z "${SLURM_JOB_ID:-}" ]]; then
    echo "Not in a Slurm job. Start an interactive session first (see the top of this script)." >&2
    exit 1
fi
if [[ $# -lt 2 ]]; then
    echo "Usage: bash scripts/berzelius-interactive.sh <samplesheet.csv> <project> [batch_size] [options]" >&2
    exit 1
fi

if [[ ! -f "$1" ]]; then
    echo "Not a samplesheet file: $1" >&2
    exit 1
fi
samplesheet="$(realpath "$1")"
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

# Each project starts Nextflow from its own folder. Nextflow resumes the last session of the
# folder it starts in, so a shared folder would mix the results of different projects.
repo="$PWD"
launch="$PROJ/runs/$project-launch"
mkdir -p "$launch"
cd "$launch"

echo "Job $SLURM_JOB_ID: $cores cores, $total_memory, samplesheet $samplesheet, batch_size $batch_size, project $project"

nextflow run "$repo" -profile local -resume \
    --input "$samplesheet" \
    --configs "${CONFIGS:-$repo/cp-configs}" \
    --outdir "$PROJ/runs" --project "$project" \
    --nf_work_dir "$PROJ/runs/$project-work" \
    --batch_size "$batch_size" \
    --total_cpus "$cores" --total_memory "$total_memory" \
    --task_cpus 1 --task_memory '7 GB' --task_time '2h' \
    "${@:4}"
