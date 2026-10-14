#!/usr/bin/env bash

# The bin/ helpers run inside the CellProfiler 4.2.8 container, which ships Python 3.8.
# Run the helper tests with that interpreter so newer-Python APIs fail here, not on a cluster.
set -euo pipefail

# Work in the repository folder, wherever the script is started from.
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Download Python 3.8 once (uv keeps it in its cache), and give its path to the tests.
# tests/test_helpers.py runs each helper script with CPNF_HELPER_PYTHON. pytest itself stays on
# the Python of .venv.
uv python install 3.8 --quiet
CPNF_HELPER_PYTHON="$(uv python find 3.8)"
export CPNF_HELPER_PYTHON
"$CPNF_HELPER_PYTHON" --version
uv run pytest -q
