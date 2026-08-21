#!/usr/bin/env bash
set -euo pipefail

PINNED_UV_VERSION="0.12.5"
PINNED_PYTHON_VERSION="3.12.14"
REPO_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
RUN_CHECKS=0

case "${1:-}" in
  "") ;;
  --check) RUN_CHECKS=1 ;;
  *)
    echo "usage: $0 [--check]" >&2
    exit 2
    ;;
esac

UV_EXECUTABLE=""
UV_PYTHON=""

if command -v uv >/dev/null 2>&1; then
  UV_EXECUTABLE="$(command -v uv)"
else
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -m uv --version >/dev/null 2>&1; then
      UV_PYTHON="$(command -v "$candidate")"
      break
    fi
  done

  if [[ -z "$UV_PYTHON" ]]; then
    for candidate in python3 python; do
      if command -v "$candidate" >/dev/null 2>&1; then
        UV_PYTHON="$(command -v "$candidate")"
        break
      fi
    done
    if [[ -z "$UV_PYTHON" ]]; then
      echo "Python is required to install the pinned uv bootstrap dependency." >&2
      exit 1
    fi
    "$UV_PYTHON" -m pip install --user --disable-pip-version-check "uv==$PINNED_UV_VERSION"
  fi
fi

run_uv() {
  if [[ -n "$UV_EXECUTABLE" ]]; then
    "$UV_EXECUTABLE" "$@"
  else
    "$UV_PYTHON" -m uv "$@"
  fi
}

cd "$REPO_ROOT"
run_uv python install "$PINNED_PYTHON_VERSION"
run_uv sync --all-extras --dev --python "$PINNED_PYTHON_VERSION"

if [[ "$RUN_CHECKS" -eq 1 ]]; then
  run_uv run ruff check .
  run_uv run ruff format --check .
  run_uv run mypy src agent scripts
  run_uv run pytest -q
  run_uv run arc3 doctor
fi
