import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).resolve().parent.parent.parent

DEFAULT_SETTINGS = {
    "language": "ru",
    "torrserver_endpoint": "http://127.0.0.1:8090",
    "jackett_url": "",
    "jackett_api_key": "",
    "player_type": "mpv",          # "mpv" | "external"
    "player_path": "",
    "embedded_player": True,
    "onboarding_complete": False,
    "minimize_to_tray": True,
    "register_magnet_handler": False,
}

def get_data_dir() -> Path:
    if getattr(sys, 'frozen', False):
        exec_name = Path(sys.executable).name.lower()
        if 'portable' in exec_name:
            if sys.platform == "win32":
                base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
            else:
                base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
            app_dir = Path(base) / "Pirate Cinema"
        else:
            app_dir = Path(sys.executable).parent
    else:
        if sys.platform == "win32":
            base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        else:
            base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
        app_dir = Path(base) / "Pirate Cinema"
    
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir

def settings_path() -> Path:
    return get_data_dir() / "settings.json"

def load_settings() -> dict[str, Any]:
    s = settings_path()
    if not s.exists():
        return DEFAULT_SETTINGS.copy()
    try:
        data = json.loads(s.read_text(encoding="utf-8"))
        merged = DEFAULT_SETTINGS.copy()
        merged.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
        return merged
    except OSError:
        logger.exception("Error loading settings")
        return DEFAULT_SETTINGS.copy()

def save_settings(data: dict[str, Any]) -> None:
    s = settings_path()
    s.parent.mkdir(parents=True, exist_ok=True)
    current = load_settings()
    current.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
    s.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
