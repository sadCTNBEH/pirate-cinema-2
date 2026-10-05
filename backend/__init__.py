import json
import sys
from pathlib import Path

if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    _base = Path(sys._MEIPASS)
else:
    _base = Path(__file__).parent.parent

_version_file = _base / "version.json"

__version__ = "error"
try:
    with open(_version_file, "r", encoding="utf-8") as f:
        __version__ = json.load(f).get("version", __version__)
except (OSError, json.JSONDecodeError):
    pass
