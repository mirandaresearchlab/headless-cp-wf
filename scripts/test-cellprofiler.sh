#!/usr/bin/env bash
# Run the full test suite, including the CellProfiler plugin tests, in the cp-headless environment.
# These tests need CellProfiler and Java, so they run locally (pre-commit) and not on GitHub.
#
# CP_ENV names the environment (default cp-headless). A value containing "/" is treated as a prefix path.
# Works with conda, mamba or micromamba, whichever is initialised in the shell.
set -euo pipefail
cd "$(dirname "$0")/.."

env="${CP_ENV:-cp-headless}"
if [[ "$env" == */* ]]; then target=(-p "$env"); else target=(-n "$env"); fi

runner="${MAMBA_EXE:-${CONDA_EXE:-}}"
if [[ -z "$runner" ]]; then
    runner="$(command -v micromamba || command -v mamba || command -v conda || true)"
fi
if [[ -z "$runner" ]]; then
    echo "No conda, mamba or micromamba found. Create the environment with: conda env create -f environment.yml" >&2
    exit 1
fi

exec "$runner" run "${target[@]}" python -m pytest -q -p no:cacheprovider tests
