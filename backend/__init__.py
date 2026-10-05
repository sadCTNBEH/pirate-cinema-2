import json
from pathlib import Path

_base = Path(__file__).parent.parent
_version_file = _base / "version.json"

__version__ = "0.0.1"
try:
    with open(_version_file, "r", encoding="utf-8") as f:
        __version__ = json.load(f).get("version", __version__)
except (OSError, json.JSONDecodeError):
    pass
