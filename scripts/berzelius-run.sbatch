#!/usr/bin/env bash
# Run the workflow on Berzelius as a Slurm batch job (the "head job").
# The head job runs Nextflow on 2 cores. Nextflow submits every CellProfiler task
# as its own Slurm job on berzelius-cpu, with the same account as the head job.
#
# Submit from the repository folder, on the login node:
#   sbatch -A <account> scripts/berzelius-run.sbatch <images> <project> [batch_size] [extra Nextflow options]
#
# images      folder with one sub-folder per plate
# project     output name under $PROJ/runs/projects/
# batch_size  image sets per CellProfiler task (default 9)
# PROJ and CP_ENV can be set in the environment to override the defaults below.
# The head job stops after 72 hours. Submit the same command again to continue (-resume).
#SBATCH -p berzelius-cpu
#SBATCH -n 1
#SBATCH -c 2
#SBATCH -t 72:00:00
#SBATCH -J cp-headless
#SBATCH -o cp-headless-%j.log
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"

if [[ $# -lt 2 ]]; then
    echo "Usage: sbatch -A <account> scripts/berzelius-run.sbatch <images> <project> [batch_size] [options]" >&2
    exit 1
fi
if [[ ! -f main.nf ]]; then
    echo "Submit from the repository folder (the folder with main.nf)." >&2
    exit 1
fi

images="$(realpath "$1")"
project="$2"
batch_size="${3:-9}"
PROJ="${PROJ:-/proj/berzelius-2025-380/users/$USER}"
CP_ENV="${CP_ENV:-$PROJ/envs/cp-headless}"

module load Miniforge3/25.3.1-0
eval "$(conda shell.bash hook)"
conda activate "$CP_ENV"
export NXF_HOME="$PROJ/.nextflow"
# Keep the Nextflow driver small: it only submits and watches jobs.
export NXF_OPTS='-Xms512m -Xmx4g'

# Each project starts Nextflow from its own folder. Nextflow resumes the last session of the
# folder it starts in, so a shared folder would mix the results of different projects.
repo="$PWD"
launch="$PROJ/runs/$project-launch"
mkdir -p "$launch"
cd "$launch"

echo "Job $SLURM_JOB_ID: account $SLURM_JOB_ACCOUNT, images $images, batch_size $batch_size, project $project"

nextflow run "$repo" -profile berzelius -resume \
    --images "$images" \
    --configs "$repo/cp-configs" \
    --outdir "$PROJ/runs" --project "$project" \
    --nf_work_dir "$PROJ/runs/$project-work" \
    --conda_cache "$PROJ/runs/conda-cache" \
    --slurm_account "$SLURM_JOB_ACCOUNT" \
    --batch_size "$batch_size" \
    "${@:4}"
