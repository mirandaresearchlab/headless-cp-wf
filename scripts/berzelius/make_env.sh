#!/usr/bin/env bash

# Write the settings file of cp-headless for Berzelius. You give the values as options, so you do not edit a file.
# Run it on a login node or in a job. The guide is docs/how-to/run-on-berzelius.md, step 4.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: scripts/berzelius/make_env.sh -p PROJ_DIR [-m MODULE] [-c CONDA_ENV] [-o OUT_FILE] [-f]

  -p PROJ_DIR   your folder in /proj, for example /proj/<project>/users/$USER
  -m MODULE     the Miniforge module. The default is Miniforge3, which loads the default version.
                To pin a version, give it: -m Miniforge3/25.3.1-0   (`module avail Miniforge3` lists them)
  -c CONDA_ENV  the conda environment with Nextflow and Java. The default is PROJ_DIR/envs/nextflow.
  -o OUT_FILE   the settings file to write. The default is PROJ_DIR/cp-headless.env.
  -f            replace OUT_FILE if it exists

The file loads Nextflow and Java, and puts the Nextflow and Apptainer caches in PROJ_DIR.
EOF
}

# Stop with a message. Exit code 2 = wrong settings (nothing was written).
fail() {
    echo "ERROR: $*" >&2
    exit 2
}

proj=""
module_name="Miniforge3"
conda_env=""
out=""
force=0
while getopts "p:m:c:o:fh" opt; do
    case "$opt" in
        p) proj="$OPTARG" ;;
        m) module_name="$OPTARG" ;;
        c) conda_env="$OPTARG" ;;
        o) out="$OPTARG" ;;
        f) force=1 ;;
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
[[ $# -eq $((OPTIND - 1)) ]] || fail "unexpected argument: ${*:OPTIND:1}"

# Check the project folder. Placeholders like <project> mean that you did not replace the example text.
[[ -n "$proj" ]] || {
    usage >&2
    fail "give your folder in /proj with -p"
}
case "$proj" in
    *"<"* | *">"*) fail "-p $proj still has a <placeholder>. Write your real project folder." ;;
    /*) ;;
    *) fail "-p must be an absolute path, for example /proj/<project>/users/\$USER" ;;
esac
proj="${proj%/}"
case "$proj/" in
    "$HOME"/*) fail "$proj is in your home directory. Use /proj: your home has only 20 GB and 1 million files." ;;
esac
[[ -d "$proj" ]] || fail "$proj does not exist. Check the path, and check that you are on Berzelius."

# The module name has no spaces or quotes: it goes into a shell file.
[[ "$module_name" =~ ^[A-Za-z0-9._/+-]+$ ]] || fail "-m $module_name is not a module name, for example Miniforge3/25.3.1-0"

# The default environment is written as $PROJ/envs/nextflow, so that the file follows a moved PROJ.
if [[ -z "$conda_env" ]]; then
    env_text='$PROJ/envs/nextflow'
else
    [[ "$conda_env" == /* ]] || fail "-c must be an absolute path"
    env_text="$conda_env"
fi
[[ -n "$out" ]] || out="$proj/cp-headless.env"
if [[ -e "$out" && "$force" -ne 1 ]]; then
    fail "$out exists. Use -f to replace it."
fi

cat >"$out" <<EOF

# Settings for cp-headless on Berzelius. The head job and smoke_test.sh read this file with bash.
# Made by scripts/berzelius/make_env.sh. Run that script again (with -f) to change a value.
# Every path is in /proj: your home folder has a quota of 20 GB and 1 million files.

export PROJ="$proj"

# Nextflow needs Java 17 to 26. Both come from the conda environment in /proj.
module load $module_name
eval "\$(conda shell.bash hook)"
conda activate "$env_text"

# Berzelius sets JAVA_CMD to the old system Java. Nextflow reads JAVA_CMD before JAVA_HOME, so remove it.
unset JAVA_CMD
export JAVA_HOME="\$CONDA_PREFIX/lib/jvm"

# Nextflow plugins and the container images: in /proj, not in \$HOME.
export NXF_HOME="\$PROJ/.nextflow"
export NXF_APPTAINER_CACHEDIR="\$PROJ/containers"
export APPTAINER_CACHEDIR="\$PROJ/containers/.apptainer-cache"
EOF

echo "Wrote $out"
echo "Next: run the test in an interactive CPU job (guide, step 5):"
echo "  bash scripts/berzelius/smoke_test.sh \"$out\" \"$proj/cp-smoke\""
