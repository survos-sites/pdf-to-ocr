#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PORT="${PORT:-5000}"
HOST="${HOST:-127.0.0.1}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python not found: $PYTHON_BIN" >&2
  exit 1
fi

if ! command -v tesseract >/dev/null 2>&1; then
  echo "Missing dependency: tesseract" >&2
  exit 1
fi

if ! command -v gs >/dev/null 2>&1; then
  echo "Missing dependency: ghostscript (gs)" >&2
  exit 1
fi

if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip
python -m pip install -r "$ROOT_DIR/requirements.txt"

exec python -m uvicorn app:app --reload --host "$HOST" --port "$PORT"
