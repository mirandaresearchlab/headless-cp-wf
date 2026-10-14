#!/usr/bin/env bash

# Prepare the development environment of cp-headless, once:
#   1. make the Python environment .venv (Python 3.12, shell prompt "cp-headless"),
#   2. install the exact tool versions from uv.lock (Nextflow, Ruff, pytest, pre-commit),
#   3. install the Git hook that runs the checks of .pre-commit-config.yaml before each commit.
# See docs/development.md.
set -euo pipefail

# Work in the repository folder, wherever the script is started from.
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# uv makes the environment and installs the tools. Stop with a link if it is missing.
command -v uv >/dev/null 2>&1 || {
    echo "ERROR: uv is required: https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
}

uv venv --python 3.12 --prompt cp-headless
uv sync --all-groups
uv run pre-commit install

echo "Development environment ready. Activate it with: source .venv/bin/activate"
