import os
import sys
from pathlib import Path

def get_data_dir() -> Path:
    if getattr(sys, 'frozen', False):
        # Running as compiled executable (PyInstaller)
        # Put data right next to the .exe (works for both portable and installed directory)
        app_dir = Path(sys.executable).parent
    else:
        # Running from source
        if sys.platform == "win32":
            base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        else:
            base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
        app_dir = Path(base) / "Pirate Cinema"
    
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir
