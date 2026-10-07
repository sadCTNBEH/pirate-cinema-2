import asyncio
import logging
import sqlite3
import time
from typing import Any

import anyio
from fastapi import HTTPException

from backend.api import deps
from backend.core.settings import load_settings
from backend.infrastructure.mpv.controller import MPVController
from backend.models.playback import PlayRequest, PlaybackState
from backend.repositories.playback import MpvRepository
from backend.services.i18n import t
from backend.infrastructure.torrserver import client
from backend.repositories import metadata, history

logger = logging.getLogger(__name__)

class MpvService:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # Если атрибут is_initialized уже есть, значит мы тут не в первый раз. Уходим!
        if hasattr(self, 'is_initialized'):
            return

        self.controller = MPVController()
        self.repository = MpvRepository()
        self.controller.on_progress = self._handle_progress
        self.controller.on_end = self._handle_end
        self.loop = None

        # Переменные для состояния и троттлинга
        self.current_state = None
        self.last_db_update = 0.0
        self.is_switching = False

        self.is_initialized = True

    async def launch(self, request: PlayRequest):
        self.loop = asyncio.get_running_loop()

        self.stop()
        self.is_switching = False

        prefs = load_settings()
        torrserver_url = deps.get_torrserver_url()

        is_series = self.repository.parse_ep(request.file_name)[0] == 1
        media_type = "series" if is_series else "movie"

        await anyio.to_thread.run_sync(
            metadata.save_media_type,
            request.hash,
            media_type,
        )
        await anyio.to_thread.run_sync(
            history.mark_played,
            request.hash,  # type: ignore
            request.file_id,  # type: ignore
            request.file_name,  # type: ignore
        )

        mpv_bin = deps.resolve_mpv_binary(prefs)
        url = client.stream_url(torrserver_url, request.hash, request.file_id, request.file_name)

        try:
            row = await anyio.to_thread.run_sync(self.repository.get_previous_progress, request.hash, request.file_id)
        except sqlite3.Error as e:
            logger.exception("Database error during playback preparation")
            raise HTTPException(
                status_code=500, detail="Ошибка базы данных при подготовке"
            ) from e

        start_time = request.start_time or 0
        audio_track = request.audio_track or 0
        subtitle_track = request.subtitle_track or 0

        if row:
            if not row["is_watched"] and row["playback_timecode"]:
                start_time = int(row["playback_timecode"])
            if not request.audio_track and row["audio_track"]:
                audio_track = int(row["audio_track"])
            if not request.subtitle_track and row["subtitle_track"]:
                subtitle_track = int(row["subtitle_track"])

        self.current_state = PlaybackState(
            hash=request.hash,
            file_id=request.file_id,
            timecode=start_time,
            duration=0,
            audio_track=audio_track,
            subtitle_track=subtitle_track,
            is_watched=False,
        )
        try:
            self.controller.launch(
                mpv_path=mpv_bin,
                url=url,
                title=request.file_name,
                start_time=start_time,
                audio_track=audio_track,
                subtitle_track=subtitle_track,
            )
        except (OSError, RuntimeError) as e:
            logger.exception("Failed to launch player process")
            raise HTTPException(
                status_code=500, detail=t("err_mpv_not_found")
            ) from e

        return "launched"

    def stop(self):
        self.controller.stop()
        return {"status": "stopped"}

    def _handle_progress(self, prop_name: str, value: Any):
        if not self.current_state:
            return None

        if prop_name == "time-pos" and value:
            self.current_state.timecode = int(float(value))

        if prop_name == "duration" and value:
            self.current_state.duration = int(float(value))

        if prop_name == "aid" and value:
            self.current_state.audio_track = int(value) if str(value).isdigit() else 0

        if prop_name == "sid" and value:
            self.current_state.subtitle_track = int(value) if str(value).isdigit() else 0

        if not self.is_switching and self.current_state.duration > 0:
            time_left = self.current_state.duration - self.current_state.timecode

            if time_left <= 1:
                self.is_switching = True
                self.current_state.is_watched = True
                self.current_state.timecode = 0
                self.repository.save_progress(self.current_state)

                def on_done(f):
                    if f.exception():
                        logger.exception(f"Autoplay failed during time-pos check")

                future = asyncio.run_coroutine_threadsafe(
                    self.play_next_file(self.current_state.hash, self.current_state.file_id),
                    self.loop
                )
                future.add_done_callback(on_done)

        now = time.time()
        if now - self.last_db_update > 5.0:
            self.repository.save_progress(self.current_state)
            self.last_db_update = now

        return 0

    def _handle_end(self, reason: str | None):
        if not self.current_state:
            return

        is_finished = False

        if self.current_state.duration > 0:
            time_left = self.current_state.duration - self.current_state.timecode
            percent_watched = self.current_state.timecode / self.current_state.duration

            if percent_watched > 0.95 or time_left < 15:
                is_finished = True

        if is_finished:
            self.current_state.is_watched = True
            self.current_state.timecode = 0

        self.repository.save_progress(self.current_state)

        if reason == "eof" and not self.is_switching:
            def on_done(f):
                if f.exception():
                    logger.exception(f"Autoplay failed on EOF event")

            future = asyncio.run_coroutine_threadsafe(
                self.play_next_file(self.current_state.hash, self.current_state.file_id),
                self.loop
            )
            future.add_done_callback(on_done)

    def sort_video_files(self, files):
        return sorted(files, key=lambda f: self.repository.parse_ep(
            f.get("name") or f.get("file_name") or f.get("path") or ""
        ))

    async def play_next_file(self, torrent_hash: str, current_file_id: int) -> bool:
        try:
            torrserver_url = deps.get_torrserver_url()
            files = await client.torrent_video_files(torrserver_url, torrent_hash)
            files = self.sort_video_files(files)

            idx = -1
            for i, f in enumerate(files):
                f_id = f.get("id") or f.get("file_id")
                if str(f_id) == str(current_file_id):
                    idx = i
                    break

            if idx >= 0 and idx + 1 < len(files):
                next_f = files[idx + 1]
                next_id = next_f.get("id") or next_f.get("file_id")

                request = PlayRequest(
                    hash=torrent_hash,
                    file_id=int(next_id),
                    file_name=next_f.get("name") or next_f.get("file_name") or "",
                    start_time=0,
                    audio_track=0,
                    subtitle_track=0,
                )

                await self.launch(request=request)
                return True

            self.stop()
            return False

        except (KeyError, ValueError, TypeError, ConnectionError, OSError) as e:
            logger.exception(f"Critical error while resolving next file for playback")
            self.stop()
            return False