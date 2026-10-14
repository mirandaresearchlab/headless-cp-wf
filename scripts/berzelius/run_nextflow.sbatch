#!/bin/bash
# Head job: runs the Nextflow driver of cp-headless on a Berzelius CPU node.
# Do not submit this file directly. Use scripts/berzelius/submit.sh: it checks the settings and sets the
# account, the CPU partition, the log file and the CPNF_* variables.
# To continue a stopped run (for example after the 72 h limit), run the same submit.sh command again.
#SBATCH -J cp-headless
#SBATCH -n 1
#SBATCH -c 2
#SBATCH -t 72:00:00

set -euo pipefail

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

# shellcheck source=/dev/null
source "$CPNF_ENV"
for name in NXF_HOME NXF_APPTAINER_CACHEDIR; do
    if [[ -z "${!name:-}" ]]; then
        echo "ERROR: $CPNF_ENV must set $name to a folder in /proj." >&2
        exit 2
    fi
done
export NXF_OPTS="${NXF_OPTS:--Xms1g -Xmx4g}"
export NXF_ANSI_LOG=false

# The run folder holds .nextflow/, the cache that -resume needs. Always start from the same folder.
cd "$CPNF_RUN_DIR"
mkdir -p pipeline_info
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
