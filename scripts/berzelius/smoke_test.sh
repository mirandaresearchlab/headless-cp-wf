#!/usr/bin/env bash

# First test of cp-headless on Berzelius. Run it in an interactive job on a CPU node, not on a login node:
#   interactive -A <account> -p berzelius-cpu -n 1 -c 4 -t 01:00:00
#   bash scripts/berzelius/smoke_test.sh /proj/<project>/users/$USER/cp-headless.env /proj/<project>/users/$USER/cp-smoke
#
# It pulls the CellProfiler image into NXF_APPTAINER_CACHEDIR, then runs the bundled test data (6 images)
# on this node. It ends with the object counts that the test data must give.
set -euo pipefail

# Two arguments: the settings file and a new test folder in /proj.
usage() { echo "Usage: $0 ENV_FILE TEST_DIR   (TEST_DIR: a new folder in /proj)" >&2; }
[[ $# -eq 2 ]] || {
    usage
    exit 2
}
env_file="$1"
test_dir="$2"
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Only inside a Slurm job (SLURM_JOB_ID is set), and only on a CPU partition. Login nodes are not
# for computing, and GPU nodes would charge GPU hours.
if [[ -z "${SLURM_JOB_ID:-}" ]]; then
    echo "ERROR: run this inside an interactive job on a CPU node, not on a login node:" >&2
    echo "  interactive -A <account> -p berzelius-cpu -n 1 -c 4 -t 01:00:00" >&2
    exit 2
fi
case "${SLURM_JOB_PARTITION:-}" in
    berzelius-cpu | berzelius-hopper-cpu) ;;
    *)
        echo "ERROR: this job runs in partition '${SLURM_JOB_PARTITION:-unknown}'. Use a CPU partition." >&2
        exit 2
        ;;
esac

# Load Nextflow, Java and the cache folders from the settings file.
# shellcheck source=/dev/null
source "$env_file"
: "${NXF_APPTAINER_CACHEDIR:?$env_file must set NXF_APPTAINER_CACHEDIR}"
mkdir -p "$test_dir" "$NXF_APPTAINER_CACHEDIR"
cd "$test_dir"

# Run the tasks on this node (local executor) instead of submitting jobs.
cat >local.config <<'EOF'
process.executor = 'local'
process.scratch = false
EOF

# Run the berzelius profile with the test data. The account and partition come from this job.
nextflow -version
apptainer --version
nextflow run "$repo" -c local.config -profile berzelius,test -ansi-log false \
    -work-dir "$test_dir/work" --outdir "$test_dir/results" \
    --slurm_account "${SLURM_JOB_ACCOUNT:?}" --slurm_partition "$SLURM_JOB_PARTITION" \
    --container_cache "$NXF_APPTAINER_CACHEDIR"

# Compare the result with the reference: 6 image sets and 51 nuclei (one table row each, minus the
# header row). Other numbers mean that CellProfiler behaves differently here than in the tests.
features="$test_dir/results/cellprofiler_tables"
image_sets=$(($(wc -l <"$features/Image.csv") - 1))
nuclei=$(($(wc -l <"$features/Nuclei.csv") - 1))
echo "Result: $image_sets image sets and $nuclei nuclei. Expected: 6 image sets and 51 nuclei."
if [[ "$image_sets" -ne 6 || "$nuclei" -ne 51 ]]; then
    echo "ERROR: the results differ from the reference. Do not start large runs." >&2
    exit 1
fi
echo "OK: CellProfiler works on Berzelius. Image cache: $NXF_APPTAINER_CACHEDIR"
