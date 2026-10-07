import os
import shutil
import sys
from pathlib import Path

from backend.core.settings import load_settings
from backend.infrastructure.mpv.controller import MPVController
from backend.services.playback import MpvService
from backend.core.settings import get_data_dir

_mpv = MPVController()


def get_torrserver_url() -> str:
    return load_settings()["torrserver_endpoint"]

def get_playback_service() -> MpvService:
    return MpvService()

def resolve_mpv_binary(prefs: dict) -> Path:
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