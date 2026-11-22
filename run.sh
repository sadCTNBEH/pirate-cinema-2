#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if command -v uv >/dev/null 2>&1; then
    if [[ ! -x .venv/bin/python ]]; then
        echo "Creating virtual environment and syncing dependencies with uv..."
        uv sync
    fi
elif [[ ! -x .venv/bin/python ]]; then
    printf '%s\n' 'Окружение .venv не найдено. Выполните в каталоге проекта:' \
        '  uv sync' \
        'или установите uv: https://docs.astral.sh/uv/' >&2
    exit 1
fi

export PIRATE_CINEMA_GUI="${PIRATE_CINEMA_GUI:-native}"
if [[ $OSTYPE == linux* ]]; then
    export PYWEBVIEW_GUI="${PYWEBVIEW_GUI:-qt}"
    if [[ -n "${DISPLAY:-}" && -z "${QT_QPA_PLATFORM:-}" ]]; then
        export QT_QPA_PLATFORM="xcb"
    fi
fi

if command -v uv >/dev/null 2>&1; then
    exec uv run --no-sync run.py "$@"
else
    exec .venv/bin/python run.py "$@"
fi
