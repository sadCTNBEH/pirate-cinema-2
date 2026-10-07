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
from backend.infrastructure.torrserver import client
from backend.models.playback import PlaybackState, PlayRequest
from backend.repositories import history, metadata
from backend.repositories.playback import MpvRepository
from backend.services.i18n import t

logger = logging.getLogger(__name__)

class MpvService:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, 'is_initialized'):
            return

        self.controllers: dict[str, MPVController] = {}
        self.active_states: dict[str, PlaybackState] = {}

        self.repository = MpvRepository()
        self.loop = None

        self.last_db_update = 0.0
        self.is_switching = False

        self.is_initialized = True

    async def launch(self, request: PlayRequest):
        self.loop = asyncio.get_running_loop()

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

        start_time = request.start_time if request.start_time is not None else 0
        audio_track = request.audio_track if request.audio_track is not None else 0
        subtitle_track = request.subtitle_track if request.subtitle_track is not None else 0

        if row:
            if request.start_time is None and not row["is_watched"] and row["playback_timecode"]:
                start_time = int(row["playback_timecode"])
            if request.audio_track is None and row["audio_track"]:
                audio_track = int(row["audio_track"])
            if request.subtitle_track is None and row["subtitle_track"]:
                subtitle_track = int(row["subtitle_track"])

        player_key = request.hash

        old_state = self.active_states.get(player_key)
        is_same_file = old_state and old_state.file_id == request.file_id

        self.active_states[player_key] = PlaybackState(
            hash=request.hash,
            file_id=request.file_id,
            timecode=start_time,
            duration=0,
            audio_track=audio_track,
            subtitle_track=subtitle_track,
            is_watched=False,
        )

        if player_key in self.controllers and self.controllers[player_key].is_running and is_same_file:
            controller = self.controllers[player_key]

            opts = []
            if start_time > 0:
                opts.append(f"start={start_time}")
            if audio_track:
                opts.append(f"aid={audio_track}")
            if subtitle_track:
                opts.append(f"sid={subtitle_track}")

            opts_str = ",".join(opts)

            if opts_str:
                controller.send_command(["loadfile", url, "replace", opts_str])
            else:
                controller.send_command(["loadfile", url, "replace"])

        else:
            if player_key in self.controllers:
                self.controllers[player_key].stop()

            controller = MPVController()
            self.controllers[player_key] = controller

            controller.on_progress = lambda name, val, k=player_key: self._handle_progress(k, name, val)
            controller.on_end = lambda reason, k=player_key: self._handle_end(k, reason)

            try:
                controller.launch(
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
        for controller in self.controllers.values():
            if controller.is_running:
                controller.stop()

        self.controllers.clear()
        self.active_states.clear()
        return {"status": "stopped"}

    def _handle_progress(self, player_key: str, prop_name: str, value: Any):
        state = self.active_states.get(player_key)
        if not state:
            return None

        if prop_name == "time-pos" and value:
            state.timecode = int(float(value))

        if prop_name == "duration" and value:
            state.duration = int(float(value))

        if prop_name == "aid" and value:
            state.audio_track = int(value) if str(value).isdigit() else 0

        if prop_name == "sid" and value:
            state.subtitle_track = int(value) if str(value).isdigit() else 0

        if not self.is_switching and state.duration > 0:
            time_left = state.duration - state.timecode

            if time_left <= 1:
                self.is_switching = True
                state.is_watched = True
                state.timecode = 0
                self.repository.save_progress(state)

                def on_done(f):
                    if f.exception():
                        logger.exception("Autoplay failed during time-pos check")

                future = asyncio.run_coroutine_threadsafe(
                    self.play_next_file(state.hash, state.file_id),
                    self.loop
                )
                future.add_done_callback(on_done)

        now = time.time()
        if now - self.last_db_update > 5.0:
            self.repository.save_progress(state)
            self.last_db_update = now

        return None

    def _handle_end(self, player_key: str, reason: str | None):
        state = self.active_states.get(player_key)
        if not state:
            return

        is_finished = False

        if state.duration > 0:
            time_left = state.duration - state.timecode
            percent_watched = state.timecode / state.duration

            if percent_watched > 0.95 or time_left < 15:
                is_finished = True

        if is_finished:
            state.is_watched = True
            state.timecode = 0

        self.repository.save_progress(state)

        if reason == "eof" and not self.is_switching:
            def on_done(f):
                if f.exception():
                    logger.exception("Autoplay failed on EOF event")

            future = asyncio.run_coroutine_threadsafe(
                self.play_next_file(state.hash, state.file_id),
                self.loop
            )
            future.add_done_callback(on_done)

    def sort_video_files(self, files):
        return sorted(files, key=lambda f: self.repository.parse_ep(
            f.get("name") or f.get("file_name") or f.get("path") or ""
        ))

    async def play_next_file(self, hash: str, file_id: int) -> bool:
        player_key = hash
        state = self.active_states.get(player_key)
        if not state:
            return False

        try:
            torrserver_url = deps.get_torrserver_url()
            files = await client.torrent_video_files(torrserver_url, hash)
            files = self.sort_video_files(files)

            idx = -1
            for i, f in enumerate(files):
                f_id = f.get("id") or f.get("file_id")
                if str(f_id) == str(file_id):
                    idx = i
                    break

            if idx >= 0 and idx + 1 < len(files):
                next_f = files[idx + 1]
                next_id = next_f.get("id") or next_f.get("file_id")

                request = PlayRequest(
                    hash=hash,
                    file_id=int(next_id),
                    file_name=next_f.get("name") or next_f.get("file_name") or "",
                    start_time=0,
                    audio_track=state.audio_track or 0,
                    subtitle_track=state.subtitle_track or 0,
                )

                await self.launch(request=request)
                return True

            self.stop()
            return False

        except (KeyError, ValueError, TypeError, ConnectionError, OSError):
            logger.exception("Critical error while resolving next file for playback")
            self.stop()
            return False

    async def get_state(self, hash, file_id):
        state = self.active_states.get(hash)

        if state and state.hash == hash and state.file_id == file_id:
            return state

        try:
            row = await anyio.to_thread.run_sync(self.repository.get_state, hash, file_id)
        except sqlite3.Error as e:
            logger.exception("Database error during playback preparation")
            raise HTTPException(
                status_code=500, detail="Ошибка базы данных при подготовке"
            ) from e

        if row:
            return PlaybackState(
                hash=hash,
                file_id=file_id,
                timecode=row["playback_timecode"] or 0,
                duration=row["playback_duration"] or 0,
                audio_track=row["audio_track"] or 0,
                subtitle_track=row["subtitle_track"] or 0,
                is_watched=row["is_watched"] or False,
            )

        raise HTTPException(status_code=404, detail="Прогресс для данного файла не найден")
