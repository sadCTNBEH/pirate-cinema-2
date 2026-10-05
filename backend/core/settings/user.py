import json
import logging
from pathlib import Path
from typing import Any

from backend.core.settings.base import get_data_dir
from backend.core.settings.config import config

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS: dict[str, Any] = {
    "language": "ru",
    "torrserver_endpoint": config.TORRSERVER_DEFAULT_URL,
    "jackett_url": "",
    "jackett_api_key": "",
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
        return merged
    except (OSError, json.JSONDecodeError):
        logger.exception("Error loading settings")
        return DEFAULT_SETTINGS.copy()


def save_settings(data: dict[str, Any]) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = load_settings()
    current.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
