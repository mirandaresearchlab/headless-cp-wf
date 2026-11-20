#!/usr/bin/env bash
# Run the headless CellProfiler workflow on a screen, one plate at a time, in one Slurm head job.
# When a plate is complete, the script deletes the Nextflow work folder of that plate and starts
# the next plate. The run then needs extra disk space for about one plate, not for all plates.
#
# Submit from the repository folder, on the login node:
#   SHEET=<samplesheet.csv> OUT=<results> sbatch -A <account> scripts/berzelius-run-plates.sbatch
#   SHEET=<samplesheet.csv> OUT=<results> sbatch -A <account> scripts/berzelius-run-plates.sbatch <plate> [...]
#
# SHEET samplesheet CSV with one row per image file (see docs/reference/file-formats.md) (required)
# OUT   folder for the results, one sub-folder per plate (required)
# The other settings below can be set in the same way, for example MAX_JOBS=96.
#
# To continue after a stop (a failure or the 72-hour limit), submit the same command again.
# The script skips plates that have a DONE file. The plate that stopped continues with -resume.
#SBATCH -p berzelius-cpu
#SBATCH -n 1
#SBATCH -c 2
#SBATCH -t 72:00:00
#SBATCH -J cp-plates
#SBATCH -o cp-plates-%j.log
set -euo pipefail

if [[ -z "${SHEET:-}" || -z "${OUT:-}" || ! -f "${SHEET:-}" ]]; then
    echo "Set SHEET (a samplesheet file) and OUT (the results folder). See the top of this script." >&2
    exit 1
fi
SHEET="$(realpath "$SHEET")"

PROJ="${PROJ:-/proj/berzelius-2025-380/users/$USER}"
REPO="${REPO:-$SLURM_SUBMIT_DIR}"                       # the workflow (main.nf)
CONFIGS="${CONFIGS:-$REPO/cp-configs}"                  # 1_illumination.cppipe and 2_analysis.cppipe
CP_ENV="${CP_ENV:-$PROJ/envs/cp-headless}"              # conda environment with CellProfiler and Nextflow
QUOTA_DIR="${QUOTA_DIR:-${PROJ%/users/*}}"              # the project storage, for nscquota
if [[ ! -f "$REPO/main.nf" ]]; then
    echo "Submit from the repository folder (the folder with main.nf)." >&2
    exit 1
fi

BATCH_SIZE="${BATCH_SIZE:-9}"
TASK_MEMORY="${TASK_MEMORY:-14 GB}"
TASK_TIME="${TASK_TIME:-4h}"
MAX_JOBS="${MAX_JOBS:-96}"

# Disk space check before a plate starts: image sets x GIB_PER_SET must be free under the quota.
# Benchmark: about 49 MB for each image set (work files, final table and masks).
CHANNELS="${CHANNELS:-5}"           # images in one image set
GIB_PER_SET="${GIB_PER_SET:-0.05}"

# Print the plates of the samplesheet, or (with a plate name) write the rows of that plate to a
# new samplesheet. Relative paths become absolute, because the new file is elsewhere.
sheet_plates() {
    python - "$SHEET" "$@" <<'EOF'
import csv, os, sys
from pathlib import Path
sheet = Path(sys.argv[1])
with sheet.open(newline='', encoding='utf-8-sig') as stream:
    reader = csv.reader(stream)
    header = [c.strip() for c in next(reader)]
    rows = [dict(zip(header, (v.strip() for v in r))) for r in reader if any(v.strip() for v in r)]
if 'plate' not in header or 'path' not in header:
    sys.exit(f'{sheet} needs the columns plate and path')
if len(sys.argv) == 2:
    print('\n'.join(sorted({r['plate'] for r in rows})))
    sys.exit()
plate, out = sys.argv[2], Path(sys.argv[3])
selected = [dict(r, path=os.path.abspath(sheet.parent / r['path'])) for r in rows if r['plate'] == plate]
if not selected:
    sys.exit(f'{sheet} has no rows for plate {plate}')
with out.open('w', newline='') as stream:
    writer = csv.DictWriter(stream, fieldnames=header, lineterminator='\n')
    writer.writeheader()
    writer.writerows(selected)
print(len(selected))
EOF
}

# Free space under the project quota (the soft limit), in GiB.
# nscquota sometimes fails for a moment (server error), so it tries three times.
# Prints nothing if all three tries fail.
free_gib() {
    local out
    for _ in 1 2 3; do
        out=$(nscquota -p "$QUOTA_DIR" 2>/dev/null | awk '
            function gib(v, u) { return u == "TiB" ? v * 1024 : u == "GiB" ? v : v / 1024 }
            /^Project quota limits/ { getline; quota = gib($1, $2) }
            /^Percent used/ { sub("%", "", $3); printf "%d\n", quota * (1 - $3 / 100) }' || true)
        if [[ -n "$out" ]]; then
            echo "$out"
            return 0
        fi
        sleep 10
    done
}

module load Miniforge3/25.3.1-0
eval "$(conda shell.bash hook)"
conda activate "$CP_ENV"
export NXF_HOME="$PROJ/.nextflow"
export NXF_OPTS='-Xms512m -Xmx4g'

if [[ $# -gt 0 ]]; then
    plates=("$@")
else
    plate_list=$(sheet_plates)          # an assignment, so set -e stops the job if this fails
    mapfile -t plates <<< "$plate_list"
fi
echo "Job $SLURM_JOB_ID: ${#plates[@]} plates from $SHEET, results in $OUT"

for plate in "${plates[@]}"; do
    dir="$OUT/$plate"
    if [[ -f "$dir/DONE" ]]; then
        echo "$plate: complete before, skipped"
        continue
    fi

    # Each plate gets its own samplesheet with only its rows. Replace it only if its rows changed:
    # a new file time would make Nextflow run PREPARE again, and with it every task.
    mkdir -p "$dir/input" "$dir/launch"
    images=$(sheet_plates "$plate" "$dir/input/samplesheet.new.csv")
    if cmp -s "$dir/input/samplesheet.new.csv" "$dir/input/samplesheet.csv"; then
        rm "$dir/input/samplesheet.new.csv"
    else
        mv "$dir/input/samplesheet.new.csv" "$dir/input/samplesheet.csv"
    fi

    # A new plate must fit under the quota. A plate that stopped already has part of its files.
    if [[ ! -d "$dir/work" ]]; then
        need=$(awk -v n="$images" -v c="$CHANNELS" -v g="$GIB_PER_SET" 'BEGIN { printf "%d\n", n / c * g + 1 }')
        free=$(free_gib || true)
        if [[ -z "$free" ]]; then
            echo "$plate: nscquota gave no answer. The disk space check is skipped." >&2
        elif (( free < need )); then
            echo "$plate: needs about $need GiB, but only $free GiB is free under the quota. Stopped." >&2
            exit 1
        else
            echo "$plate: $images images, needs about $need GiB, $free GiB free"
        fi
    fi

    # Each plate has its own launch folder, so -resume continues the session of this plate only.
    cd "$dir/launch"
    if ! nextflow run "$REPO" -profile berzelius -resume \
        --input "$dir/input/samplesheet.csv" --configs "$CONFIGS" \
        --outdir "$dir" --project "$plate" \
        --nf_work_dir "$dir/work" \
        --slurm_account "$SLURM_JOB_ACCOUNT" \
        --batch_size "$BATCH_SIZE" --task_memory "$TASK_MEMORY" \
        --task_time "$TASK_TIME" --max_jobs "$MAX_JOBS"; then
        echo "$plate: Nextflow failed. The work files stay for -resume. Fix the cause, then submit again." >&2
        exit 1
    fi

    # Delete the work files only when the workflow recorded success and wrote the final table.
    marker=$(find "$dir/projects" -mindepth 2 -maxdepth 2 -name run.json 2>/dev/null | head -n 1 || true)
    results=$(dirname "$marker")
    status=$(ls -t "$results"/logs/status-*.json 2>/dev/null | head -n 1 || true)
    if [[ -z "$marker" || -z "$status" || ! -s "$results/cp_features/$plate.parquet" ]] \
        || ! grep -q '"success": *true' "$status"; then
        echo "$plate: no successful result found in $dir/projects. The work files stay." >&2
        exit 1
    fi
    rm -rf "$dir/work"
    echo "$results" > "$dir/DONE"
    echo "$plate: complete. Results in $results. Work files deleted."
done

echo "All plates complete."
