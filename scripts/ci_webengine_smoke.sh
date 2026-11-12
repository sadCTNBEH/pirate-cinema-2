#!/usr/bin/env bash
set -euo pipefail

scratch=""
pulse_module=""
log=""
cleanup() {
    if [[ -n "$pulse_module" ]]; then
        pactl unload-module "$pulse_module" || true
    fi
    if [[ -n "$scratch" ]]; then
        rm -rf -- "$scratch"
    fi
    if [[ -n "$log" ]]; then
        rm -f -- "$log"
    fi
}
trap cleanup EXIT

if [[ -z "${XDG_DATA_HOME:-}" ]]; then
    scratch=$(mktemp -d)
    export XDG_DATA_HOME="$scratch"
fi
export XDG_CACHE_HOME="$XDG_DATA_HOME/cache"
export XDG_CONFIG_HOME="$XDG_DATA_HOME/config"
export PIRATE_CINEMA_GUI=native PYWEBVIEW_GUI=qt QT_API=pyqt6 QT_QPA_PLATFORM=xcb
pulseaudio --start --exit-idle-time=-1
sink="pirate_webengine_ci_$$"
pulse_module=$(pactl load-module module-null-sink "sink_name=$sink")
log=$(mktemp)

set +e
PULSE_SINK="$sink" "$@" --smoke-test-webengine 2>&1 | tee "$log"
status=${PIPESTATUS[0]}
set -e

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    {
        echo '### Qt WebEngine / Chromium'
        echo '```text'
        if ! grep -E '\[WEBENGINE\].*(chromium=|chromium_security_patch=)|\[WEBENGINE-SMOKE\]' "$log"; then
            echo 'WebEngine version diagnostics were not emitted; the functional smoke result determines job status.'
        fi
        echo '```'
    } >> "$GITHUB_STEP_SUMMARY"
fi
exit "$status"
