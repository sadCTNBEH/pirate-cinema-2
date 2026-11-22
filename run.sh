#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

export PIRATE_CINEMA_GUI="${PIRATE_CINEMA_GUI:-native}"
if [[ $OSTYPE == linux* ]]; then
    export PYWEBVIEW_GUI="${PYWEBVIEW_GUI:-qt}"
    if [[ -n "${DISPLAY:-}" && -z "${QT_QPA_PLATFORM:-}" ]]; then
        export QT_QPA_PLATFORM="xcb"
    fi
fi

# 1. If uv is available, use it for dependency management and execution
if command -v uv >/dev/null 2>&1; then
    if [[ ! -x .venv/bin/python ]]; then
        echo "Virtual environment not found. Initializing with uv sync..."
        if ! uv sync --frozen; then
            echo "Fallback: resolving dependencies with uv sync..."
            uv sync
        fi
    fi
    exec uv run --no-sync run.py "$@"
fi

# 2. Fallback if uv is not installed, but .venv exists
if [[ -x .venv/bin/python ]]; then
    echo "[INFO] uv is not installed, but existing .venv found. Starting..." >&2
    exec .venv/bin/python run.py "$@"
fi

# 3. Neither uv nor .venv found
printf '%s\n' \
    '[ERROR] uv is not installed and no existing virtual environment was found.' \
    'Pirate Cinema uses uv for fast, reliable dependency management.' \
    '' \
    'To install uv on Linux / macOS, run:' \
    '  curl -LsSf https://astral.sh/uv/install.sh | sh' \
    '' \
    'Or via package managers:' \
    '  brew install uv' \
    '  pip install uv' \
    '' \
    'Documentation: https://docs.astral.sh/uv/' >&2
exit 1
