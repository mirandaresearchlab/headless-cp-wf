#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Nextflow: the one on PATH, else the one that `uv sync` installs into .venv.
if ! command -v nextflow >/dev/null 2>&1; then
    if [[ -x "$repo_root/.venv/bin/nextflow" ]]; then
        export PATH="$repo_root/.venv/bin:$PATH"
    else
        echo "ERROR: Nextflow is not on PATH. Run ./scripts/bootstrap.sh or install Nextflow." >&2
        exit 1
    fi
fi

# Nextflow supports Java 17 through 26. Keep the selected JVM if it is supported, else find one.
java_major() {
    "$1" -version 2>&1 | sed -nE '1s/.*version "(1\.)?([0-9]+).*/\2/p'
}
supported() {
    local major
    major="$(java_major "$1" 2>/dev/null || true)"
    [[ -n "$major" && "$major" -ge 17 && "$major" -le 26 ]]
}
current_java="${JAVA_CMD:-${JAVA_HOME:+$JAVA_HOME/bin/java}}"
current_java="${current_java:-$(command -v java || true)}"
if [[ -z "$current_java" ]] || ! supported "$current_java"; then
    candidates=()
    for major in 21 17 25 24 23 22 26 20 19 18; do
        if [[ -x /usr/libexec/java_home ]]; then
            home="$(/usr/libexec/java_home -v "$major" 2>/dev/null || true)"
            [[ -n "$home" ]] && candidates+=("$home")
        fi
        candidates+=("/opt/homebrew/opt/openjdk@$major" "/usr/local/opt/openjdk@$major")
    done
    candidates+=(/usr/lib/jvm/*)
    found=""
    for home in "${candidates[@]}"; do
        if [[ -x "$home/bin/java" ]] && supported "$home/bin/java"; then
            found="$home"
            break
        fi
    done
    if [[ -z "$found" ]]; then
        echo "ERROR: Nextflow needs Java 17 to 26, but ${current_java:-no Java} is not supported" \
            "and no supported JDK was found. Install one, for example: brew install openjdk@21" >&2
        exit 1
    fi
    export JAVA_HOME="$found"
    unset JAVA_CMD
    export PATH="$JAVA_HOME/bin:$PATH"
    echo "Using Java $(java_major "$JAVA_HOME/bin/java") from $JAVA_HOME"
fi

stub_test_dir="$(mktemp -d "${TMPDIR:-/tmp}/cp-headless-stub.XXXXXX")"
cleanup() {
    rm -rf -- "$stub_test_dir"
}
trap cleanup EXIT

# Launch outside the repository and keep every generated file in the temporary
# directory. The EXIT trap removes results, work files, cache, reports, and logs
# whether the test succeeds or fails.
cd "$stub_test_dir"
nextflow -log "$stub_test_dir/.nextflow.log" run "$repo_root" \
    -profile test,local \
    -stub-run \
    -ansi-log false \
    -work-dir "$stub_test_dir/work" \
    --outdir "$stub_test_dir/results"
