#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

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

nextflow run . -profile test,local -stub-run -ansi-log false

