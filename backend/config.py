import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

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

SETTINGS_PATH = get_data_dir() / "settings.json"

DEFAULT_SETTINGS = {
    "lang": "ru",
    "torrserver_url": "http://127.0.0.1:8090",
    "external_player": "",
    "jackett_url": "",
    "jackett_key": "",
    "auto_update": True,
}

def load_settings() -> Dict[str, Any]:
    if not SETTINGS_PATH.exists():
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS.copy()
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            settings = json.load(f)
            merged = DEFAULT_SETTINGS.copy()
            merged.update(settings)
            return merged
    except Exception as e:
        print(f"Error loading settings: {e}")
        return DEFAULT_SETTINGS.copy()

def save_settings(settings: Dict[str, Any]) -> None:
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving settings: {e}")
