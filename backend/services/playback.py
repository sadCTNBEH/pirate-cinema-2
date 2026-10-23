import asyncio
import inspect
import logging
import sqlite3
import time
from collections.abc import Callable
from contextlib import suppress
from typing import Any

import anyio
import httpx

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
        library_repo: LibraryRepository | None = None,
        metadata_service: Any = None,
        online_repo: Any = None,
        online_service: Any = None,
    ):
        self._repo = playback_repo
        self._history = history_repo
        self._metadata = metadata_repo
        self._controller_factory = mpv_controller_factory
        self._torrserver = torrserver_client
        self._get_ts_url = settings_provider
        self._library_repo = library_repo
        self._metadata_service = metadata_service
        self._online_repo = online_repo
        self._online_service = online_service

        self.controllers: dict[str, MPVController] = {}
        self.active_states: dict[str, PlaybackState] = {}

        self.loop: asyncio.AbstractEventLoop | None = None
        self.last_db_update: float = 0.0
        self.is_switching: bool = False
        self._last_cycle_pause_time: float = 0.0
        self._last_cycle_mute_time: float = 0.0

    async def launch(self, command: PlayCommand) -> str:
        self.loop = asyncio.get_running_loop()
        self.is_switching = False

        prefs = load_settings()
        torrserver_url = self._get_ts_url()

        parsed_ep = LibraryRepository.parse_ep(command.file_name)
        is_series = parsed_ep[0] == 1
        season = parsed_ep[1] if is_series else None
        episode = parsed_ep[2] if is_series else None
        media_type = "series" if is_series else "movie"

        if not command.hash.startswith("online:"):
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
                None,
                season,
                episode,
            )

            # Ensure torrent title and record exist in library
            title_for_db = command.file_name or command.hash
            if self._library_repo:
                await anyio.to_thread.run_sync(
                    self._library_repo.ensure_torrent,
                    command.hash,
                    title_for_db,
                )
                if hasattr(self._torrserver, "torrent_video_files"):
                    try:
                        res = self._torrserver.torrent_video_files(
                            torrserver_url, command.hash
                        )
                        ts_files = await res if inspect.isawaitable(res) else (res if isinstance(res, list) else None)
                        if ts_files and isinstance(ts_files, list):
                            await anyio.to_thread.run_sync(
                                self._library_repo.save_total_files,
                                command.hash,
                                len(ts_files),
                            )
                    except (httpx.HTTPError, ExternalServiceError, OSError, RuntimeError, ValueError):
                        pass
            else:
                await anyio.to_thread.run_sync(
                    self._metadata.save_metadata_title,
                    command.hash,
                    title_for_db,
                )

            # Persist torrent in TorrServer DB so it is retained in the library
            if hasattr(self._torrserver, "save_torrent_to_db"):
                try:
                    res = self._torrserver.save_torrent_to_db(
                        torrserver_url, command.hash, title_for_db
                    )
                    if inspect.isawaitable(res):
                        await res
                except (httpx.HTTPError, ValueError) as e:
                    logger.debug("Failed to save torrent to TorrServer DB on launch: %s", e)

            # Trigger metadata enrichment in background
            if self._metadata_service:
                try:
                    res = self._metadata_service.trigger_metadata_fetch(
                        command.hash, title_for_db
                    )
                    if inspect.isawaitable(res):
                        await res
                except (ExternalServiceError, ValueError) as e:
                    logger.debug("Failed to trigger metadata fetch on launch: %s", e)

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

        is_watched = False
        duration = 0
        if row:
            r_dict = dict(row)
            is_watched = bool(r_dict.get("is_watched"))
            if r_dict.get("playback_duration"):
                duration = int(r_dict["playback_duration"])
            if (
                command.start_time is None
                and not is_watched
                and row["playback_timecode"]
            ):
                start_time = int(row["playback_timecode"])
            if command.audio_track is None and row["audio_track"]:
                audio_track = int(row["audio_track"])
            if command.subtitle_track is None and row["subtitle_track"]:
                subtitle_track = int(row["subtitle_track"])

        start_time = max(0, start_time)
        if duration > 0 and start_time > duration:
            start_time = duration

        player_key = command.hash

        running_controller: MPVController | None = None
        for k, c in list(self.controllers.items()):
            if c.is_running:
                running_controller = c
                break

        # Защита от случайного перезапуска текущего видеофайла с 0-й секунды
        existing_state = self.active_states.get(player_key)
        if (
            running_controller
            and existing_state
            and existing_state.hash == command.hash
            and existing_state.file_id == command.file_id
            and (command.start_time is None or command.start_time == 0)
        ):
            logger.info(
                "Ignoring duplicate launch for currently playing hash %s file %s",
                command.hash,
                command.file_id,
            )
            return "launched"

        self.active_states[player_key] = PlaybackState(
            hash=command.hash,
            file_id=command.file_id,
            timecode=start_time,
            duration=duration,
            audio_track=audio_track,
            subtitle_track=subtitle_track,
            is_watched=is_watched,
            file_name=command.file_name,
            is_ready=False,
        )

        if running_controller:
            self.controllers.clear()
            self.active_states.clear()
            self.controllers[player_key] = running_controller
            self.active_states[player_key] = PlaybackState(
                hash=command.hash,
                file_id=command.file_id,
                timecode=start_time,
                duration=duration,
                audio_track=audio_track,
                subtitle_track=subtitle_track,
                is_watched=is_watched,
                file_name=command.file_name,
                is_ready=False,
            )

            running_controller.on_progress = lambda name, val, k=player_key: (
                self._handle_progress(k, name, val)
            )
            running_controller.on_end = lambda reason, k=player_key: self._handle_end(k, reason)

            opts = ["pause=no", f"start={start_time}"]
            if audio_track:
                opts.append(f"aid={audio_track}")
            if subtitle_track:
                opts.append(f"sid={subtitle_track}")
            opts_str = ",".join(opts)

            running_controller.send_command(["set_property", "start", "none"])
            running_controller.send_command(
                ["set_property", "force-media-title", command.file_name]
            )
            if audio_track:
                running_controller.send_command(["set_property", "aid", audio_track])
            if subtitle_track:
                running_controller.send_command(["set_property", "sid", subtitle_track])
            running_controller.send_command(["loadfile", url, "replace", -1, opts_str])
            running_controller.send_command(["set_property", "pause", False])

        else:
            self.controllers.clear()
            self.active_states.clear()

            self.active_states[player_key] = PlaybackState(
                hash=command.hash,
                file_id=command.file_id,
                timecode=start_time,
                duration=duration,
                audio_track=audio_track,
                subtitle_track=subtitle_track,
                is_watched=is_watched,
                file_name=command.file_name,
                is_ready=False,
            )

            controller = self._controller_factory()
            self.controllers[player_key] = controller

            controller.on_progress = lambda name, val, k=player_key: (
                self._handle_progress(k, name, val)
            )
            controller.on_end = lambda reason, k=player_key: self._handle_end(k, reason)

            wid: int | None = None
            if prefs.get("embedded_player", True):
                with suppress(Exception):
                    from backend.gui import window_api

                    wid = window_api.ensure_player_hwnd()

            launch_kwargs: dict[str, Any] = {
                "mpv_path": mpv_bin,
                "url": url,
                "title": command.file_name,
                "start_time": start_time,
                "audio_track": audio_track,
                "subtitle_track": subtitle_track,
            }
            if wid is not None:
                launch_kwargs["wid"] = wid

            try:
                controller.launch(**launch_kwargs)
            except (OSError, RuntimeError) as e:
                logger.exception("Failed to launch player process")
                raise ExternalServiceError(
                    t("err_mpv_not_found"), status_code=500
                ) from e

        return "launched"

    async def launch_online(
        self,
        provider: str,
        video_id: str,
        stream_url: str,
        title: str,
        start_time: int = 0,
        thumbnail: str | None = None,
        duration: int | None = None,
        playlist_id: str | None = None,
        episode_index: int | None = None,
        quality: str | None = None,
    ) -> str:
        self.loop = asyncio.get_running_loop()
        self.is_switching = False

        prefs = load_settings()
        player_key = f"online:{provider}:{video_id}"

        if self._online_repo:
            try:
                await anyio.to_thread.run_sync(
                    self._online_repo.mark_played,
                    provider,
                    video_id,
                    title,
                    thumbnail,
                    duration,
                )
            except sqlite3.Error as e:
                logger.warning("Failed to record online playback in history: %s", e)

            if start_time == 0:
                try:
                    prev = await anyio.to_thread.run_sync(
                        self._online_repo.get_progress, provider, video_id
                    )
                    if prev and not prev.get("is_watched") and prev.get("playback_timecode"):
                        start_time = int(prev["playback_timecode"])
                except (sqlite3.Error, ValueError, TypeError) as e:
                    logger.debug("Failed to retrieve previous online progress: %s", e)

        running_controller: MPVController | None = None
        for k, c in list(self.controllers.items()):
            if c.is_running:
                running_controller = c
                break

        existing_online_state = self.active_states.get(player_key)
        if (
            running_controller
            and existing_online_state
            and existing_online_state.hash == player_key
            and start_time == 0
        ):
            logger.info("Ignoring duplicate launch for currently playing online stream %s", player_key)
            return "launched"

        self.active_states[player_key] = PlaybackState(
            hash=player_key,
            file_id=0,
            timecode=start_time,
            duration=duration or 0,
            file_name=title,
            is_online=True,
            online_provider=provider,
            online_id=video_id,
            playlist_id=playlist_id,
            episode_index=episode_index,
        )

        mpv_bin = resolve_mpv_binary(prefs)

        if running_controller:
            self.controllers.clear()
            self.active_states.clear()
            self.controllers[player_key] = running_controller
            self.active_states[player_key] = PlaybackState(
                hash=player_key,
                file_id=0,
                timecode=start_time,
                duration=duration or 0,
                file_name=title,
                is_online=True,
                online_provider=provider,
                online_id=video_id,
                playlist_id=playlist_id,
                episode_index=episode_index,
                is_ready=False,
            )

            running_controller.on_progress = lambda name, val, k=player_key: (
                self._handle_progress(k, name, val)
            )
            running_controller.on_end = lambda reason, k=player_key: self._handle_end(k, reason)

            opts = ["pause=no", f"start={start_time}"]
            opts_str = ",".join(opts)

            running_controller.send_command(["set_property", "start", "none"])
            running_controller.send_command(["set_property", "force-media-title", title])
            running_controller.send_command(["loadfile", stream_url, "replace", -1, opts_str])
            running_controller.send_command(["set_property", "pause", False])
        else:
            self.controllers.clear()
            self.active_states.clear()

            self.active_states[player_key] = PlaybackState(
                hash=player_key,
                file_id=0,
                timecode=start_time,
                duration=duration or 0,
                file_name=title,
                is_online=True,
                online_provider=provider,
                online_id=video_id,
                playlist_id=playlist_id,
                episode_index=episode_index,
                is_ready=False,
            )

            controller = self._controller_factory()
            self.controllers[player_key] = controller

            controller.on_progress = lambda name, val, k=player_key: (
                self._handle_progress(k, name, val)
            )
            controller.on_end = lambda reason, k=player_key: self._handle_end(k, reason)

            wid: int | None = None
            if prefs.get("embedded_player", True):
                with suppress(Exception):
                    from backend.gui import window_api

                    wid = window_api.ensure_player_hwnd()

            launch_kwargs: dict[str, Any] = {
                "mpv_path": mpv_bin,
                "url": stream_url,
                "title": title,
                "start_time": start_time,
            }
            if wid is not None:
                launch_kwargs["wid"] = wid

            try:
                controller.launch(**launch_kwargs)
            except (OSError, RuntimeError) as e:
                logger.exception("Failed to launch player process for online stream")
                raise ExternalServiceError(
                    t("err_mpv_not_found"), status_code=500
                ) from e

        return "launched"

    def stop(self) -> dict[str, str]:
        current_controllers = list(self.controllers.values())
        self.controllers.clear()
        self.active_states.clear()

        for controller in current_controllers:
            if controller.is_running:
                try:
                    controller.stop()
                except (OSError, RuntimeError) as error:
                    logger.debug("Failed to stop MPV controller: %s", error)

        with suppress(Exception):
            from backend.gui import window_api

            window_api.hide_player_panel()
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
        with suppress(Exception):
            from backend.gui import window_api

            window_api.hide_player_panel()

    def _handle_progress(self, player_key: str, prop_name: str, value: Any) -> None:
        if prop_name == "fullscreen":
            with suppress(Exception):
                from backend.gui import window_api

                window_api.set_fullscreen(bool(value))
            return

        state = self.active_states.get(player_key)
        if not state:
            return

        if prop_name in ("time-pos", "playback-time"):
            tc = _parse_timecode(value)
            if tc is not None:
                state.timecode = max(0, tc)
                if state.duration > 0 and state.timecode > state.duration:
                    state.timecode = state.duration
            state.is_ready = True

        elif prop_name == "duration":
            dur = _parse_timecode(value)
            if dur is not None:
                state.duration = max(0, dur)
                state.timecode = min(state.timecode, state.duration)

        elif prop_name == "aid":
            aid = _parse_track_id(value)
            if aid is not None:
                state.audio_track = aid

        elif prop_name == "sid":
            sid = _parse_track_id(value)
            if sid is not None:
                state.subtitle_track = sid

        elif prop_name == "pause":
            state.is_paused = bool(value)

        elif prop_name == "mute":
            state.is_muted = bool(value)

        elif prop_name == "paused-for-cache":
            state.is_buffering = bool(value)

        elif prop_name == "volume":
            with suppress(Exception):
                state.volume = round(float(value))

        elif prop_name == "track-list":
            if isinstance(value, list):
                state.track_list = value

        is_eof = (prop_name == "eof-reached" and bool(value)) or (
            prop_name == "time-pos"
            and state.duration > 0
            and state.timecode > 10
            and ((state.duration - state.timecode) <= 2.0 or (state.timecode / state.duration) >= 0.90)
        )

        if is_eof:
            if not self.is_switching and self.loop:
                self.is_switching = True
                state.is_watched = True
                if state.duration > 0:
                    state.timecode = state.duration

                asyncio.run_coroutine_threadsafe(
                    self._save_state_to_db(state), self.loop
                )
                if getattr(state, "is_online", False):
                    if state.playlist_id and state.episode_index is not None:
                        fut = asyncio.run_coroutine_threadsafe(
                            self.play_next_online(state.playlist_id, state.episode_index), self.loop
                        )
                        fut.add_done_callback(lambda f: self._on_play_next_done(f, player_key))
                    else:
                        self.is_switching = False
                else:
                    fut = asyncio.run_coroutine_threadsafe(
                        self.play_next_file(state.hash, state.file_id), self.loop
                    )
                    fut.add_done_callback(lambda f: self._on_play_next_done(f, player_key))
            return

        now = time.time()
        is_flush = prop_name == "flush"
        if (is_flush or (now - self.last_db_update >= 5.0)) and self.loop:
            self.last_db_update = now
            if state.duration > 0 and ((state.duration - state.timecode) <= 180 or (state.timecode / state.duration) >= 0.90):
                state.is_watched = True

            asyncio.run_coroutine_threadsafe(self._save_state_to_db(state), self.loop)

    def _on_play_next_done(self, fut: Any, player_key: str) -> None:
        with suppress(Exception):
            exc = fut.exception()
            if exc:
                logger.error(
                    "play_next_file failed for %s: %s",
                    player_key,
                    exc,
                    exc_info=exc,
                )
                self.is_switching = False
                return

            res = fut.result()
            if not res:
                self.is_switching = False
                return

        if self.loop and self.loop.is_running():
            self.loop.call_later(1.5, self._reset_switching)
        else:
            self.is_switching = False

    def _reset_switching(self) -> None:
        self.is_switching = False

    def _handle_end(self, player_key: str, reason: str | None = None) -> None:
        if self.is_switching:
            logger.debug(
                "Ignoring _handle_end for %s during active file switch (reason=%s)",
                player_key,
                reason,
            )
            return

        state = self.active_states.get(player_key)

        if state and self.loop:
            if reason == "eof" or (
                state.duration > 0 and (state.duration - state.timecode) < 180
            ):
                state.is_watched = True

            asyncio.run_coroutine_threadsafe(self._save_state_to_db(state), self.loop)

        if reason in ("quit", "error"):
            logger.info(
                "Playback ended with reason '%s', stopping player %s",
                reason,
                player_key,
            )
            controller = self.controllers.pop(player_key, None)
            if controller and controller.is_running:
                controller.stop()
            self.active_states.pop(player_key, None)
            if not self.controllers:
                with suppress(Exception):
                    from backend.gui import window_api

                    window_api.hide_player_panel()
            return

        if reason == "eof" and not self.is_switching and self.loop and state:
            self.is_switching = True
            if getattr(state, "is_online", False):
                if state.playlist_id and state.episode_index is not None:
                    fut = asyncio.run_coroutine_threadsafe(
                        self.play_next_online(state.playlist_id, state.episode_index), self.loop
                    )
                    fut.add_done_callback(lambda f: self._on_play_next_done(f, player_key))
                else:
                    self.is_switching = False
            else:
                fut = asyncio.run_coroutine_threadsafe(
                    self.play_next_file(state.hash, state.file_id), self.loop
                )
                fut.add_done_callback(lambda f: self._on_play_next_done(f, player_key))
            return

        if reason == "stop" or not reason:
            controller = self.controllers.get(player_key)
            if controller and not controller.is_running:
                self.controllers.pop(player_key, None)
                self.active_states.pop(player_key, None)
                if not self.controllers:
                    with suppress(Exception):
                        from backend.gui import window_api

                        window_api.hide_player_panel()
            return

    async def _save_state_to_db(self, state: PlaybackState) -> None:
        if getattr(state, "is_online", False):
            if self._online_repo and state.online_provider and state.online_id:
                try:
                    await anyio.to_thread.run_sync(
                        self._online_repo.update_progress,
                        state.online_provider,
                        state.online_id,
                        state.timecode,
                        state.duration,
                    )
                except sqlite3.Error as e:
                    logger.exception("Database error while auto-saving online state")
                    raise DatabaseError("Ошибка сохранения прогресса онлайн в БД") from e
            return

        try:
            await anyio.to_thread.run_sync(self._repo.save_progress, state)
        except sqlite3.Error as e:
            logger.exception("Database error while auto-saving state")
            raise DatabaseError("Ошибка сохранения прогресса в БД") from e

    def sort_video_files(self, files: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            files,
            key=lambda f: LibraryRepository.sort_key(
                f.get("name") or f.get("file_name") or f.get("path") or ""
            ),
        )

    async def play_next_file(self, hash: str, file_id: int) -> bool:
        player_key = hash
        state = self.active_states.get(player_key)
        if not state:
            self.is_switching = False
            return False

        if hash.startswith("online:") or getattr(state, "is_online", False):
            if state.playlist_id and state.episode_index is not None:
                return await self.play_next_online(state.playlist_id, state.episode_index)
            self.is_switching = False
            return False

        try:
            torrserver_url = self._get_ts_url()
            files = await self._torrserver.torrent_video_files(torrserver_url, hash)
            files = self.sort_video_files(files)

            idx = -1
            for i, f in enumerate(files):
                f_id = f.get("id") if f.get("id") is not None else f.get("file_id")
                if str(f_id) == str(file_id):
                    idx = i
                    break

            if idx >= 0 and idx + 1 < len(files):
                next_f = files[idx + 1]
                next_id = (
                    next_f.get("id")
                    if next_f.get("id") is not None
                    else next_f.get("file_id")
                )

                cmd = PlayCommand(
                    hash=hash,
                    file_id=int(next_id),
                    file_name=next_f.get("name") or next_f.get("file_name") or "",
                    start_time=0,
                    audio_track=state.audio_track or 0,
                    subtitle_track=state.subtitle_track or 0,
                )

                await self.launch(command=cmd)
                return True

            logger.info("No next file in torrent %s; stopping player", hash)
            self.is_switching = False
            self.stop()
            return False

        except (
            httpx.HTTPError,
            ExternalServiceError,
            sqlite3.Error,
            OSError,
            ValueError,
            KeyError,
            RuntimeError,
            TypeError,
        ):
            logger.exception("Error while resolving next file for playback")
            self.is_switching = False
            self.stop()
            return False

    async def play_next_online(self, playlist_id: str, current_index: int) -> bool:
        if not self._online_repo or not self._online_service:
            self.is_switching = False
            return False

        try:
            pl = await anyio.to_thread.run_sync(
                self._online_repo.get_playlist, playlist_id
            )
            if not pl or not pl.items:
                self.is_switching = False
                return False

            next_idx = current_index + 1
            if next_idx < len(pl.items):
                next_item = pl.items[next_idx]
                stream_info = await self._online_service.resolve_stream(
                    next_item.provider, next_item.id
                )
                await self.launch_online(
                    provider=next_item.provider,
                    video_id=next_item.id,
                    stream_url=stream_info.url,
                    title=stream_info.title,
                    start_time=0,
                    thumbnail=stream_info.thumbnail,
                    duration=stream_info.duration,
                    playlist_id=playlist_id,
                    episode_index=next_idx,
                )
                return True

            logger.info("End of playlist %s reached; stopping player", playlist_id)
            self.is_switching = False
            self.stop()
            return False

        except (
            sqlite3.Error,
            ExternalServiceError,
            NotFoundError,
            ValueError,
            KeyError,
            IndexError,
        ) as err:
            logger.warning("Error advancing online playlist %s: %s", playlist_id, err)
            self.is_switching = False
            self.stop()
            return False

    def get_active_playback(self) -> dict[str, Any]:
        is_fs = False
        with suppress(Exception):
            from backend.gui import window_api

            is_fs = window_api.is_fullscreen()

        for player_key, controller in list(self.controllers.items()):
            state = self.active_states.get(player_key)
            if controller.is_running and state:
                return {
                    "active": True,
                    "hash": state.hash,
                    "file_id": state.file_id,
                    "file_name": state.file_name,
                    "timecode": state.timecode,
                    "duration": state.duration,
                    "audio_track": state.audio_track,
                    "subtitle_track": state.subtitle_track,
                    "is_watched": state.is_watched,
                    "is_fullscreen": is_fs,
                    "is_paused": getattr(state, "is_paused", False),
                    "volume": getattr(state, "volume", 100),
                    "is_muted": state.is_muted,
                    "is_buffering": state.is_buffering,
                    "is_online": getattr(state, "is_online", False),
                    "is_ready": getattr(state, "is_ready", False),
                    "online_provider": getattr(state, "online_provider", None),
                    "online_id": getattr(state, "online_id", None),
                    "playlist_id": getattr(state, "playlist_id", None),
                    "episode_index": getattr(state, "episode_index", None),
                    "track_list": getattr(state, "track_list", []),
                }
        return {
            "active": False,
            "is_fullscreen": is_fs,
            "is_paused": False,
            "volume": 100,
            "track_list": [],
        }

    def send_command(self, cmd: list[Any]) -> None:
        if cmd and len(cmd) >= 2 and cmd[0] == "cycle" and cmd[1] == "pause":
            now = time.time()
            if now - self._last_cycle_pause_time < 0.25:
                return
            self._last_cycle_pause_time = now
        elif cmd and len(cmd) >= 2 and cmd[0] == "cycle" and cmd[1] == "mute":
            now = time.time()
            if now - self._last_cycle_mute_time < 0.25:
                return
            self._last_cycle_mute_time = now

        for controller in list(self.controllers.values()):
            if controller.is_running:
                controller.send_command(cmd)

    def set_fullscreen(self, fullscreen: bool | None = None) -> bool:
        from backend.gui import window_api

        is_fs = (
            window_api.toggle_fullscreen()
            if fullscreen is None
            else window_api.set_fullscreen(fullscreen)
        )
        for controller in list(self.controllers.values()):
            if controller.is_running:
                controller.send_command(["set_property", "fullscreen", is_fs])
        return is_fs

    async def get_state(self, hash: str, file_id: int) -> PlaybackState:
        state = self.active_states.get(hash)

        if state and state.hash == hash and state.file_id == file_id:
            return state

        if hash.startswith("online:"):
            parts = hash.split(":", 2)
            if len(parts) == 3 and self._online_repo:
                provider, item_id = parts[1], parts[2]
                try:
                    row = await anyio.to_thread.run_sync(
                        self._online_repo.get_progress, provider, item_id
                    )
                except sqlite3.Error as e:
                    logger.exception("Database error during online state retrieval")
                    raise DatabaseError("Ошибка базы данных при подготовке") from e

                if row:
                    return PlaybackState(
                        hash=hash,
                        file_id=file_id,
                        timecode=row.get("playback_timecode") or 0,
                        duration=row.get("playback_duration") or 0,
                        is_watched=bool(row.get("is_watched")),
                        file_name=row.get("title") or "",
                        is_online=True,
                        online_provider=provider,
                        online_id=item_id,
                    )
            raise NotFoundError("Прогресс для данного онлайн-видео не найден")

        try:
            row = await anyio.to_thread.run_sync(self._repo.get_state, hash, file_id)
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

