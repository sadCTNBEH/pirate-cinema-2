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

# 1. Check if uv is in PATH or common user bin directories
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

# 2. If uv is not found, automatically install it
if ! command -v uv >/dev/null 2>&1; then
    echo "[INFO] uv is not installed. Installing uv automatically..." >&2
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- https://astral.sh/uv/install.sh | sh
    elif command -v python3 >/dev/null 2>&1; then
        python3 -m pip install --user uv
    fi
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

# 3. Run with uv
if [[ $OSTYPE == linux* ]]; then
    entrypoint="scripts/linux_qt_launcher.py"
else
    entrypoint="run.py"
fi

if command -v uv >/dev/null 2>&1; then
    if [[ ! -x .venv/bin/python ]]; then
        echo "Virtual environment not found. Initializing with uv sync..."
        if ! uv sync --frozen; then
            echo "Fallback: resolving dependencies with uv sync..."
            uv sync
        fi
    fi
    exec uv run --no-sync "$entrypoint" "$@"
fi

# 4. Fallback if automatic installation failed (e.g. offline) but .venv exists
if [[ -x .venv/bin/python ]]; then
    echo "[WARN] uv could not be installed, using existing .venv..." >&2
    exec .venv/bin/python "$entrypoint" "$@"
fi

# 5. Neither uv nor .venv available
printf '%s\n' \
    '[ERROR] Failed to automatically install uv.' \
    'Please install uv manually:' \
    '  curl -LsSf https://astral.sh/uv/install.sh | sh' \
    '' \
    'Documentation: https://docs.astral.sh/uv/' >&2
exit 1
