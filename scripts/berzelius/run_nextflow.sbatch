#!/bin/bash

# Head job: runs the Nextflow driver of cp-headless on a Berzelius CPU node.
# Do not submit this file directly. Use scripts/berzelius/submit.sh: it checks the settings and sets the
# account, the CPU partition, the log file and the CPNF_* variables.
# To continue a stopped run (for example after the 72 h limit), run the same submit.sh command again.

# Resources of the head job: 1 task with 2 cores for 72 hours (the Berzelius maximum). Nextflow itself
# needs little: the CellProfiler work runs in separate jobs that Nextflow submits.
# Slurm reads these lines only if they come before the first command of the script.
#SBATCH -J cp-headless
#SBATCH -n 1
#SBATCH -c 2
#SBATCH -t 72:00:00

set -euo pipefail

# submit.sh sets these four variables. Stop at once if one is missing.
: "${CPNF_REPO:?set by submit.sh}" "${CPNF_PARAMS:?set by submit.sh}"
: "${CPNF_RUN_DIR:?set by submit.sh}" "${CPNF_ENV:?set by submit.sh}"

# The driver needs no GPU. On a GPU partition, the project would pay for an idle GPU for 72 h.
case "${SLURM_JOB_PARTITION:-}" in
    berzelius-cpu | berzelius-hopper-cpu) ;;
    *)
        echo "ERROR: the head job runs in partition '${SLURM_JOB_PARTITION:-unknown}'." \
            "Submit it to berzelius-cpu or berzelius-hopper-cpu with submit.sh." >&2
        exit 2
        ;;
esac

# Load the user's settings: Nextflow, Java, and the cache folders in /proj. Two of them are required.
# shellcheck source=/dev/null
source "$CPNF_ENV"
for name in NXF_HOME NXF_APPTAINER_CACHEDIR; do
    if [[ -z "${!name:-}" ]]; then
        echo "ERROR: $CPNF_ENV must set $name to a folder in /proj." >&2
        exit 2
    fi
done

# Memory of the Nextflow program itself (Java), and a plain log without screen colors.
export NXF_OPTS="${NXF_OPTS:--Xms1g -Xmx4g}"
export NXF_ANSI_LOG=false

# The run folder holds .nextflow/, the cache that -resume needs. Always start from the same folder.
cd "$CPNF_RUN_DIR"
mkdir -p pipeline_info

# Write the job, the node and the tool versions into the log, for later questions.
echo "Head job ${SLURM_JOB_ID:-?} on $(hostname): account ${SLURM_JOB_ACCOUNT:-?}, partition $SLURM_JOB_PARTITION"
nextflow -version
apptainer --version

# Tasks use the same account and CPU partition as this head job. Reports get the job ID, so that a
# resubmitted head job does not overwrite the reports of the previous one.
nextflow run "$CPNF_REPO" \
    -profile berzelius \
    -params-file "$CPNF_PARAMS" \
    -work-dir "$CPNF_RUN_DIR/work" \
    -resume \
    -with-trace "pipeline_info/trace_${SLURM_JOB_ID:-local}.txt" \
    -with-report "pipeline_info/report_${SLURM_JOB_ID:-local}.html" \
    -with-timeline "pipeline_info/timeline_${SLURM_JOB_ID:-local}.html" \
    --slurm_account "${SLURM_JOB_ACCOUNT:?}" \
    --slurm_partition "$SLURM_JOB_PARTITION" \
    --container_cache "$NXF_APPTAINER_CACHEDIR" \
    "$@"
