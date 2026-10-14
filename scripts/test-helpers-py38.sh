#!/usr/bin/env bash
set -euo pipefail

# The bin/ helpers run inside the CellProfiler 4.2.8 container, which ships Python 3.8.
# Run the helper tests with that interpreter so newer-Python APIs fail here, not on a cluster.
cd "$(dirname "${BASH_SOURCE[0]}")/.."

uv python install 3.8 --quiet
CPNF_HELPER_PYTHON="$(uv python find 3.8)"
export CPNF_HELPER_PYTHON
"$CPNF_HELPER_PYTHON" --version
uv run pytest -q
