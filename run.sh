#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if [[ ! -x .venv/bin/python ]]; then
    printf '%s\n' 'Окружение .venv не найдено. Выполните в каталоге проекта:' \
        '  python3 -m venv .venv' \
        "  .venv/bin/python -m pip install -r requirements.txt 'pywebview[qt6]'" >&2
    exit 1
fi

export PIRATE_CINEMA_GUI="${PIRATE_CINEMA_GUI:-native}"
if [[ $OSTYPE == linux* ]]; then
    export PYWEBVIEW_GUI="${PYWEBVIEW_GUI:-qt}"
    if [[ -n "${DISPLAY:-}" && -z "${QT_QPA_PLATFORM:-}" ]]; then
        export QT_QPA_PLATFORM="xcb"
    fi
fi
exec .venv/bin/python run.py "$@"
