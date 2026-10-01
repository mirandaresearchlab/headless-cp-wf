#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

command -v nextflow >/dev/null 2>&1 || {
    echo "ERROR: Nextflow is not on PATH." >&2
    exit 1
}

# Nextflow currently supports Java 17 through 26. Prefer Homebrew's Java 21 when
# the caller has not selected another JVM.
if [[ -z "${JAVA_HOME:-}" && -x /opt/homebrew/opt/openjdk@21/bin/java ]]; then
    export JAVA_HOME=/opt/homebrew/opt/openjdk@21
    export PATH="$JAVA_HOME/bin:$PATH"
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
