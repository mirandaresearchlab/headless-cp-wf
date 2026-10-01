#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

command -v uv >/dev/null 2>&1 || {
    echo "ERROR: uv is required: https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
}

uv venv --python 3.12 --prompt cp-headless
uv sync --all-groups
uv run pre-commit install

echo "Development environment ready. Activate it with: source .venv/bin/activate"

