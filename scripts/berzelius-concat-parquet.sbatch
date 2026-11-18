#!/usr/bin/env bash
# Join the per-plate cell tables of a plate-by-plate run into one Parquet table.
# The work is done by scripts/concat_plate_tables.py. Its top describes the output and the checks.
#
# Submit from the repository folder, on the login node:
#   sbatch -A <account> scripts/berzelius-concat-parquet.sbatch <results>
#   sbatch -A <account> scripts/berzelius-concat-parquet.sbatch <results> --per-plate
#
# <results> is the OUT folder of scripts/berzelius-run-plates.sbatch.
# The first run downloads DuckDB with uv into UV_CACHE_DIR (in project storage, not in home).
#SBATCH -p berzelius-cpu
#SBATCH -n 1
#SBATCH -c 8
#SBATCH --mem=60G
#SBATCH -t 12:00:00
#SBATCH -J concat-parquet
#SBATCH -o concat-parquet-%j.log
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage: sbatch -A <account> scripts/berzelius-concat-parquet.sbatch <results> [--per-plate] [--out <path>]" >&2
    exit 1
fi
if [[ ! -f scripts/concat_plate_tables.py ]]; then
    echo "Submit from the repository folder (the folder with scripts/)." >&2
    exit 1
fi

PROJ="${PROJ:-/proj/berzelius-2025-380/users/$USER}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$PROJ/.uv-cache}"

module load uv/0.13.5

# DuckDB gets most of the job memory. Data above the limit spills to a temporary folder next to the output.
memory_gb=$(( SLURM_MEM_PER_NODE * 3 / 4 / 1024 ))
echo "Job $SLURM_JOB_ID: $SLURM_CPUS_PER_TASK threads, DuckDB memory limit ${memory_gb}GB"
uv run --python 3.12 scripts/concat_plate_tables.py "$@" --threads "$SLURM_CPUS_PER_TASK" --memory "${memory_gb}GB"
