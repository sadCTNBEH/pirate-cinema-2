import asyncio
import logging
import os
import re
import shutil
import sys
from pathlib import Path

import anyio

from backend.api import deps
from backend.api.deps import _load_settings, _mpv
from backend.api.routers.etc import sort_video_files
from backend.core.config import get_data_dir
from backend.handlers.player import PlaybackSessionHandler
from backend.infrastructure.torrserver import client as torrserver
from backend.repositories import audio, db, history, metadata

logger = logging.getLogger(__name__)

def _sync_db_prep(req_hash: str, file_id: int, file_name: str):
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT playback_timecode, is_watched FROM media_file_history WHERE torrent_hash=? AND file_index=?",
            (req_hash, file_id)
        ).fetchone()

    audio_track = audio.get_audio_track(req_hash, file_id)

    m = re.search(r"S\d+E\d+|\d+x\d+|(?:ep|episode|e)\s*\d+", file_name, re.IGNORECASE)
    metadata.save_media_type(req_hash, "series" if m else "movie")
    history.mark_played(req_hash, file_id, file_name)

    return row, audio_track


def resolve_mpv_binary(prefs: dict) -> Path:
    if sys.platform == "win32":
        mpv_bin = get_data_dir() / "vendor" / "mpv" / "mpv.exe"
        if not mpv_bin.is_file():
            prog_files = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "MPV Player" / "mpv.exe"
            if prog_files.is_file():
                mpv_bin = prog_files
    else:
        mpv_bin = get_data_dir() / "vendor" / "mpv" / "mpv"

    if not mpv_bin.is_file():
        which_mpv = shutil.which("mpv")
        mpv_bin = Path(which_mpv) if which_mpv else Path("mpv")

    return mpv_bin


async def start_playback(
    torrent_hash: str, file_id: int, file_name: str, start_time: int = 0
) -> str:
    """Основной сценарий запуска воспроизведения."""
    prefs = _load_settings()

    # 1. Запуск во внешнем плеере
    if prefs.get("player_type") == "external" and prefs.get("player_path"):
        player = Path(prefs["player_path"])
        if not player.is_file():
            raise FileNotFoundError("External player executable not found")
        url = torrserver.stream_url(
            deps._torrserver_url, torrent_hash, file_id, file_name
        )
        await asyncio.create_subprocess_exec(str(player), url)
        return "launched_external"

    # 2. Поиск бинарника и подготовка стрима
    mpv_bin = resolve_mpv_binary(prefs)
    url = torrserver.stream_url(
        deps._torrserver_url, torrent_hash, file_id, file_name
    )

    # 3. Чтение сохраненного прогресса из БД
    row, audio_track = await anyio.to_thread.run_sync(
        _sync_db_prep, torrent_hash, file_id, file_name
    )
    if row and not row["is_watched"] and row["playback_timecode"]:
        start_time = row["playback_timecode"]

    # 4. Регистрация обработчика событий сессии из отдельного модуля
    session_handler = PlaybackSessionHandler(
        torrent_hash=torrent_hash,
        file_id=file_id,
        loop=asyncio.get_running_loop(),
        play_next_fn=play_next_file,
    )

    _mpv.on_progress = session_handler.on_progress
    _mpv.on_end = session_handler.on_end

    # 5. Запуск плеера
    _mpv.launch(str(mpv_bin), url, file_name, start_time, audio_track)
    return "launched"


async def play_next_file(torrent_hash: str, current_file_id: int) -> bool:
    """Находит и запускает следующий видеофайл из раздачи."""
    files = await torrserver.torrent_video_files(deps._torrserver_url, torrent_hash)
    files = sort_video_files(files)

    idx = next((i for i, f in enumerate(files) if f["id"] == current_file_id), -1)

    if idx >= 0 and idx + 1 < len(files):
        next_f = files[idx + 1]
        await start_playback(
            torrent_hash, next_f["id"], next_f["name"], start_time=0
        )
        return True

    return False
