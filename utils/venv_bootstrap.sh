#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

python3 "$SCRIPT_DIR/git_ssh_startup.py"
python3 "$SCRIPT_DIR/venv_activate.py"

# Activate in the current shell only if sourced
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  source "$PROJECT_ROOT/.venv/bin/activate"
  echo "Bootstrapped and activated: $(which python)"
else
  echo "NOTE: Run this with:"
  echo "  source ./utils/venv_bootstrap.sh"
fi