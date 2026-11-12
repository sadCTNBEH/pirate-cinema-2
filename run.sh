#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if [[ ! -x .venv/bin/python ]]; then
    if ! command -v python3 >/dev/null || ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 12))'; then
        printf '%s\n' 'Pirate Cinema требует Python 3.12 или новее.' >&2
        exit 1
    fi
    python3 -m venv .venv
fi
.venv/bin/python scripts/bootstrap_source.py

export PIRATE_CINEMA_GUI="${PIRATE_CINEMA_GUI:-native}"
if [[ $OSTYPE == linux* ]]; then
    export PYWEBVIEW_GUI="${PYWEBVIEW_GUI:-qt}"
    if [[ -n "${DISPLAY:-}" && -z "${QT_QPA_PLATFORM:-}" ]]; then
        export QT_QPA_PLATFORM="xcb"
    fi
    exec .venv/bin/python scripts/linux_qt_launcher.py "$@"
fi
exec .venv/bin/python run.py "$@"
