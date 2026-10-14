#!/usr/bin/env bash

# Check the settings for a cp-headless run on Berzelius, then submit the head job.
# Run it on a login node. The guide is docs/how-to/run-on-berzelius.md, step 7.
set -euo pipefail

# The folder of this script, and the repository folder two levels up (the workflow to run).
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$script_dir/../.." && pwd)"

usage() {
    cat <<'EOF'
Usage: scripts/berzelius/submit.sh -A ACCOUNT -s SYSTEM -e ENV_FILE -p PARAMS_FILE -r RUN_DIR [-n] [-- NEXTFLOW_ARGS]

  -A ACCOUNT      project account, as `projinfo` shows it
  -s SYSTEM       ampere (CPU partition berzelius-cpu) or hopper (berzelius-hopper-cpu)
  -e ENV_FILE     settings file, made from scripts/berzelius/berzelius.env.example
  -p PARAMS_FILE  YAML or JSON with pipeline, input_dir, outdir, group_regex, chunk_size, ...
  -r RUN_DIR      run folder in /proj. It holds work/, logs/ and the -resume cache.
  -n              check and show the sbatch command, but do not submit

To continue a stopped run, run the same command again with the same RUN_DIR.
Text after -- goes to `nextflow run`, for example: -- --chunk_size 100
EOF
}

# Stop with a message. Exit code 2 = wrong settings (nothing was submitted).
fail() {
    echo "ERROR: $*" >&2
    exit 2
}

# Make a path absolute. The head job starts in another folder, so relative paths would break.
absolute() {
    case "$1" in
        /*) printf '%s\n' "$1" ;;
        *) printf '%s\n' "$PWD/$1" ;;
    esac
}

# Read the options. Everything after "--" goes unchanged to `nextflow run`.
account="" system="" env_file="" params="" run_dir="" dry_run=0
while getopts ":A:s:e:p:r:nh" option; do
    case "$option" in
        A) account="$OPTARG" ;;
        s) system="$OPTARG" ;;
        e) env_file="$(absolute "$OPTARG")" ;;
        p) params="$(absolute "$OPTARG")" ;;
        r) run_dir="$(absolute "$OPTARG")" ;;
        n) dry_run=1 ;;
        h)
            usage
            exit 0
            ;;
        *)
            usage >&2
            exit 2
            ;;
    esac
done
shift $((OPTIND - 1))
[[ "${1:-}" == "--" ]] && shift

# All five options are required.
[[ -n "$account" && -n "$system" && -n "$env_file" && -n "$params" && -n "$run_dir" ]] || {
    usage >&2
    exit 2
}

# The system decides the CPU partition. A GPU partition is not possible with this script.
# The name of the login node shows the system, so warn if it does not agree with -s.
case "$system" in
    ampere) partition=berzelius-cpu ;;
    hopper) partition=berzelius-hopper-cpu ;;
    *) fail "-s must be ampere or hopper, not '$system'. CellProfiler runs on CPU partitions only." ;;
esac
case "$(hostname)" in
    *hopper*) [[ "$system" == hopper ]] || echo "WARNING: this looks like a Hopper login node, but -s is $system." >&2 ;;
    *berzelius*) [[ "$system" == ampere ]] || echo "WARNING: this looks like an Ampere login node, but -s is $system." >&2 ;;
esac

# The files must exist. sbatch --export separates its values with commas, so paths must have none.
# The run folder must not be in $HOME (20 GB and 1 million files on Berzelius).
[[ -f "$env_file" ]] || fail "settings file not found: $env_file"
[[ -f "$params" ]] || fail "params file not found: $params"
for path in "$run_dir" "$env_file" "$params" "$repo"; do
    [[ "$path" != *,* ]] || fail "paths must not contain commas (sbatch --export): $path"
done
home="$(cd "$HOME" && pwd -P)"
case "$run_dir/" in
    "$home"/* | "$HOME"/*) fail "RUN_DIR $run_dir is in your home directory (20 GB, 1 million files). Use /proj/<project>/users/$USER/..." ;;
esac

# Two head jobs in one run folder would fight over the -resume cache.
if command -v squeue >/dev/null 2>&1; then
    if squeue -u "$USER" -h -o '%j %Z' | grep -Fxq "cp-headless $run_dir"; then
        fail "a cp-headless head job already runs in $run_dir. Wait for it, or cancel it first."
    fi
fi

# The sbatch command: account, CPU partition, start folder (-D) and log file of the head job.
# The CPNF_* variables tell run_nextflow.sbatch where the workflow, the params and the settings are.
command=(
    sbatch -A "$account" -p "$partition" -D "$run_dir" -o "$run_dir/logs/head-%j.out"
    --export="ALL,CPNF_REPO=$repo,CPNF_PARAMS=$params,CPNF_RUN_DIR=$run_dir,CPNF_ENV=$env_file"
    "$script_dir/run_nextflow.sbatch" "$@"
)

# With -n, show the command and stop. Otherwise make the log folder and submit.
echo "Reminder: Berzelius does not allow sensitive personal data (for example GDPR-protected data)."
if [[ "$dry_run" == 1 ]]; then
    printf 'Dry run. The command would be:\n '
    printf ' %q' "${command[@]}"
    printf '\n'
    exit 0
fi
mkdir -p "$run_dir/logs"
"${command[@]}"
echo "Log of the head job: $run_dir/logs/head-<job id>.out"
