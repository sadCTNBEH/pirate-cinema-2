import json
import logging
from pathlib import Path
from typing import Any

from backend.core.settings.base import get_data_dir
from backend.core.settings.config import config

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS: dict[str, Any] = {
    "language": "ru",
    "torrserver_url": config.TORRSERVER_DEFAULT_URL,
    "torrserver_endpoint": config.TORRSERVER_DEFAULT_URL,
    "jackett_url": "",
    "jackett_api_key": "",
    "jackett_key": "",
    "player_type": "mpv",  # "mpv" | "external"
    "player_path": "",
    "embedded_player": True,
    "onboarding_complete": False,
    "minimize_to_tray": True,
    "register_magnet_handler": False,
}


def settings_path() -> Path:
    return get_data_dir() / "settings.json"


def load_settings() -> dict[str, Any]:
    path = settings_path()
    if not path.exists():
        return DEFAULT_SETTINGS.copy()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        merged = DEFAULT_SETTINGS.copy()
        merged.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
        
        # Sync aliases
        ts_url = merged.get("torrserver_url") or merged.get("torrserver_endpoint") or config.TORRSERVER_DEFAULT_URL
        merged["torrserver_url"] = ts_url
        merged["torrserver_endpoint"] = ts_url
        
        j_key = merged.get("jackett_api_key") or merged.get("jackett_key") or ""
        merged["jackett_api_key"] = j_key
        merged["jackett_key"] = j_key
        
        return merged
    except (OSError, json.JSONDecodeError):
        logger.exception("Error loading settings")
        return DEFAULT_SETTINGS.copy()


def save_settings(data: dict[str, Any]) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = load_settings()
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


def get_torrserver_url() -> str:
    return load_settings().get("torrserver_endpoint", config.TORRSERVER_DEFAULT_URL)


def resolve_mpv_binary(prefs: dict[str, Any] | None = None) -> Path:
    import os
    import shutil
    import sys

    if prefs is None:
        prefs = load_settings()
    if prefs.get("player_path"):
        custom_path = Path(prefs["player_path"])
        if custom_path.is_file():
            return custom_path

    if sys.platform == "win32":
        mpv_bin = get_data_dir() / "vendor" / "mpv" / "mpv.exe"
        if not mpv_bin.is_file():
            prog_files = (
                Path(os.environ.get("ProgramFiles", "C:/Program Files"))
                / "MPV Player"
                / "mpv.exe"
            )
            if prog_files.is_file():
                mpv_bin = prog_files
    else:
        mpv_bin = get_data_dir() / "vendor" / "mpv" / "mpv"

    if not mpv_bin.is_file():
        which_mpv = shutil.which("mpv")
        mpv_bin = Path(which_mpv) if which_mpv else Path("mpv")

    return mpv_bin

