import asyncio
import logging
import sqlite3
import time
from collections.abc import Callable
from typing import Any

import anyio

from backend.core.settings import (
    load_settings,
    resolve_mpv_binary,
)
from backend.exceptions import DatabaseError, ExternalServiceError, NotFoundError
from backend.infrastructure.mpv.controller import MPVController
from backend.models.playback import PlaybackState, PlayCommand
from backend.repositories.history import HistoryRepository
from backend.repositories.library import LibraryRepository
from backend.repositories.metadata import MetadataRepository
from backend.repositories.playback import PlaybackRepository
from backend.services.i18n import t

logger = logging.getLogger(__name__)


def _parse_timecode(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        val = int(float(value))
        return max(0, val)
    except (ValueError, TypeError):
        return None


def _parse_track_id(value: Any) -> int | None:
    if value is None or value is True:
        return None
    if value is False:
        return 0
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("no", "off"):
            return 0
        if v in ("auto", "none", ""):
            return None
    try:
        val = int(float(value))
        return max(0, val)
    except (ValueError, TypeError):
        return None


class PlaybackService:
    def __init__(
        self,
        playback_repo: PlaybackRepository,
        history_repo: HistoryRepository,
        metadata_repo: MetadataRepository,
        mpv_controller_factory: Callable[[], MPVController],
        torrserver_client: Any,
        settings_provider: Callable[[], str],
    ):
        self._repo = playback_repo
        self._history = history_repo
        self._metadata = metadata_repo
        self._controller_factory = mpv_controller_factory
        self._torrserver = torrserver_client
        self._get_ts_url = settings_provider

        self.controllers: dict[str, MPVController] = {}
        self.active_states: dict[str, PlaybackState] = {}

        self.loop: asyncio.AbstractEventLoop | None = None
        self.last_db_update: float = 0.0
        self.is_switching: bool = False

    async def launch(self, command: PlayCommand) -> str:
        self.loop = asyncio.get_running_loop()
        self.is_switching = False

        prefs = load_settings()
        torrserver_url = self._get_ts_url()

        is_series = LibraryRepository.parse_ep(command.file_name)[0] == 1
        media_type = "series" if is_series else "movie"

        await anyio.to_thread.run_sync(
            self._metadata.save_media_type,
            command.hash,
            media_type,
        )
        await anyio.to_thread.run_sync(
            self._history.mark_played,
            command.hash,
            command.file_id,
            command.file_name,
        )

        mpv_bin = resolve_mpv_binary(prefs)
        url = self._torrserver.stream_url(
            torrserver_url, command.hash, command.file_id, command.file_name
        )

        try:
            row = await anyio.to_thread.run_sync(
                self._repo.get_previous_progress, command.hash, command.file_id
            )
        except sqlite3.Error as e:
            logger.exception("Database error during playback preparation")
            raise DatabaseError("Ошибка базы данных при подготовке") from e

        start_time = command.start_time if command.start_time is not None else 0
        audio_track = command.audio_track if command.audio_track is not None else 0
        subtitle_track = (
            command.subtitle_track if command.subtitle_track is not None else 0
        )

        if row:
            if (
                command.start_time is None
                and not row["is_watched"]
                and row["playback_timecode"]
            ):
                start_time = int(row["playback_timecode"])
            if command.audio_track is None and row["audio_track"]:
                audio_track = int(row["audio_track"])
            if command.subtitle_track is None and row["subtitle_track"]:
                subtitle_track = int(row["subtitle_track"])

        player_key = command.hash

        old_state = self.active_states.get(player_key)
        is_same_file = old_state and old_state.file_id == command.file_id

        self.active_states[player_key] = PlaybackState(
            hash=command.hash,
            file_id=command.file_id,
            timecode=start_time,
            duration=0,
            audio_track=audio_track,
            subtitle_track=subtitle_track,
            is_watched=False,
        )

        if (
            player_key in self.controllers
            and self.controllers[player_key].is_running
            and is_same_file
        ):
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

            controller = self._controller_factory()
            self.controllers[player_key] = controller

            controller.on_progress = (
                lambda name, val, k=player_key: self._handle_progress(
                    k, name, val
                )
            )
            controller.on_end = (
                lambda reason, k=player_key: self._handle_end(k, reason)
            )

            try:
                controller.launch(
                    mpv_path=mpv_bin,
                    url=url,
                    title=command.file_name,
                    start_time=start_time,
                    audio_track=audio_track,
                    subtitle_track=subtitle_track,
                )
            except (OSError, RuntimeError) as e:
                logger.exception("Failed to launch player process")
                raise ExternalServiceError(
                    t("err_mpv_not_found"), status_code=500
                ) from e

        return "launched"

    def stop(self) -> dict[str, str]:
        for controller in self.controllers.values():
            if controller.is_running:
                controller.stop()

        self.controllers.clear()
        self.active_states.clear()
        return {"status": "stopped"}

    async def stop_all(self) -> None:
        """Gracefully terminate all MPV controller processes upon application shutdown."""
        for player_key, controller in list(self.controllers.items()):
            try:
                if controller.is_running:
                    controller.stop()
            except (OSError, RuntimeError) as e:
                logger.warning(
                    "Error stopping player %s on shutdown: %s", player_key, e
                )
        self.controllers.clear()
        self.active_states.clear()

    def _handle_progress(
        self, player_key: str, prop_name: str, value: Any
    ) -> None:
        state = self.active_states.get(player_key)
        if not state:
            return

        if prop_name == "time-pos":
            tc = _parse_timecode(value)
            if tc is not None:
                state.timecode = tc

        elif prop_name == "duration":
            dur = _parse_timecode(value)
            if dur is not None:
                state.duration = dur

        elif prop_name == "aid":
            aid = _parse_track_id(value)
            if aid is not None:
                state.audio_track = aid

        elif prop_name == "sid":
            sid = _parse_track_id(value)
            if sid is not None:
                state.subtitle_track = sid

        now = time.time()
        is_flush = prop_name == "flush"
        if (is_flush or (now - self.last_db_update >= 5.0)) and self.loop:
            self.last_db_update = now
            if state.duration > 0 and (state.duration - state.timecode) < 180:
                state.is_watched = True

            asyncio.run_coroutine_threadsafe(
                self._save_state_to_db(state), self.loop
            )

    def _handle_end(self, player_key: str, reason: str) -> None:
        state = self.active_states.get(player_key)

        if state and self.loop:
            if state.duration > 0 and (state.duration - state.timecode) < 180:
                state.is_watched = True

            asyncio.run_coroutine_threadsafe(
                self._save_state_to_db(state), self.loop
            )

        if not self.is_switching and self.loop and state:
            asyncio.run_coroutine_threadsafe(
                self.play_next_file(state.hash, state.file_id), self.loop
            )

    async def _save_state_to_db(self, state: PlaybackState) -> None:
        try:
            await anyio.to_thread.run_sync(self._repo.save_progress, state)
        except sqlite3.Error as e:
            logger.exception("Database error while auto-saving state")
            raise DatabaseError("Ошибка сохранения прогресса в БД") from e

    def sort_video_files(
        self, files: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return sorted(
            files,
            key=lambda f: LibraryRepository.parse_ep(
                f.get("name") or f.get("file_name") or f.get("path") or ""
            ),
        )

    async def play_next_file(self, hash: str, file_id: int) -> bool:
        player_key = hash
        state = self.active_states.get(player_key)
        if not state:
            return False

        try:
            torrserver_url = self._get_ts_url()
            files = await self._torrserver.torrent_video_files(
                torrserver_url, hash
            )
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

                cmd = PlayCommand(
                    hash=hash,
                    file_id=int(next_id),
                    file_name=next_f.get("name")
                    or next_f.get("file_name")
                    or "",
                    start_time=0,
                    audio_track=state.audio_track or 0,
                    subtitle_track=state.subtitle_track or 0,
                )

                await self.launch(command=cmd)
                return True

            self.stop()
            return False

        except (KeyError, ValueError, TypeError, ConnectionError, OSError):
            logger.exception(
                "Critical error while resolving next file for playback"
            )
            self.stop()
            return False

    async def get_state(self, hash: str, file_id: int) -> PlaybackState:
        state = self.active_states.get(hash)

        if state and state.hash == hash and state.file_id == file_id:
            return state

        try:
            row = await anyio.to_thread.run_sync(
                self._repo.get_state, hash, file_id
            )
        except sqlite3.Error as e:
            logger.exception("Database error during playback preparation")
            raise DatabaseError("Ошибка базы данных при подготовке") from e

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

        raise NotFoundError("Прогресс для данного файла не найден")
