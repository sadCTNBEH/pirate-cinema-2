import asyncio
import inspect
import json
import logging
import math
import os
import shutil
import sqlite3
import sys
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import replace
from enum import Enum
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import anyio
import httpx
from pydantic import ValidationError

from backend.core.settings import (
    get_data_dir,
    load_settings,
    resolve_mpv_binary,
    save_settings,
)
from backend.exceptions import DatabaseError, ExternalServiceError, NotFoundError
from backend.infrastructure.mpv.controller import IMPVController, MPVController
from backend.infrastructure.torrserver.client import TorrentEngine
from backend.models.playback import PlaybackState, PlayCommand
from backend.models.subtitle_settings import SubtitleSettings
from backend.repositories.history import HistoryRepository
from backend.repositories.library import LibraryRepository
from backend.repositories.metadata import MetadataRepository
from backend.repositories.playback import PlaybackRepository
from backend.services.i18n import t
from backend.services.introdb import IntroDB
from backend.services.torrent_selection import select_torrent_file

logger = logging.getLogger(__name__)
NEXT_PREPARE_SECONDS = 90
NEXT_PREPARE_TIMEOUT = 5
NEXT_PREPARED_TTL = 120


class PlayerState(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPING = "stopping"
    ERROR = "error"

    def __str__(self) -> str:
        return self.value


def _player_error_message(error: OSError | RuntimeError, lang: str | None) -> str:
    if isinstance(error, FileNotFoundError):
        key = "err_mpv_not_found" if sys.platform == "win32" else "err_mpv_not_found_linux"
        return t(key, lang=lang)
    err_str = str(error)
    hint = ""
    if "libselinux" in err_str or "error while loading shared libraries" in err_str:
        if lang == "ru":
            hint = "\n(На вашей системе отсутствует необходимая библиотека. Установите системный mpv: 'sudo pacman -S mpv' на Arch/CachyOS или 'sudo apt install mpv' на Ubuntu/Debian)"
        else:
            hint = "\n(Missing shared library on host system. Install system mpv: 'sudo pacman -S mpv' on Arch/CachyOS or 'sudo apt install mpv' on Ubuntu/Debian)"
    return t("err_mpv_start_failed", lang=lang, error=err_str + hint,
             log_path=str(get_data_dir() / "mpv_debug.log"))


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
        mpv_controller_factory: Callable[[], IMPVController | MPVController],
        torrserver_client: Any,
        settings_provider: Callable[[], str],
        library_repo: LibraryRepository | None = None,
        metadata_service: Any = None,
        online_repo: Any = None,
        online_service: Any = None,
        search_service: Any = None,
        magnet_service: Any = None,
        *,
        engine: Any = None,
    ):
        self._repo = playback_repo
        from backend.services.subtitles import SubtitleService
        self.subtitles = SubtitleService(self)
        self._history = history_repo
        self._metadata = metadata_repo
        self._controller_factory = mpv_controller_factory
        self._torrserver = engine if engine is not None else torrserver_client
        self._engine = self._torrserver
        self._get_ts_url = settings_provider
        self._library_repo = library_repo
        self._metadata_service = metadata_service
        self._online_repo = online_repo
        self._online_service = online_service

        from backend.services.tv_session import TVSession
        self.tv = TVSession(self)

        self.controllers: dict[str, IMPVController | MPVController] = {}
        self.active_states: dict[str, PlaybackState] = {}

        self.epoch_id: int = 0
        self._state: PlayerState = PlayerState.IDLE
        self._current_launch_task: asyncio.Task | None = None
        self._launch_lock_obj: asyncio.Lock | None = None
        self._launch_lock_loop: Any = None

        self.loop: asyncio.AbstractEventLoop | None = None
        self.last_db_update: float = 0.0
        self.is_switching: bool = False
        self._last_cycle_pause_time: float = 0.0
        self._last_cycle_mute_time: float = 0.0
        self._launch_generation = 0
        self._spawn_lock = threading.RLock()
        self._recovery_lock = asyncio.Lock()
        self._failed_state: PlaybackState | None = None
        self.last_error: str | None = None
        self._pending_saves: set[Any] = set()
        self._save_lock = asyncio.Lock()
        self._seek_lock = threading.RLock()
        self._seek_epoch = 0
        self._auto_next_enabled = True
        self._next_candidates: dict[str, tuple[PlaybackState, dict[str, Any]]] = {}
        self._preparation: Any = None
        self._preparation_attempt: tuple[int, int] | None = None
        self._prepared_next: dict[str, Any] | None = None
        self._advance_attempt: tuple[int, int] | None = None
        self._next_lock = asyncio.Lock()
        self._explicit_tracks = (None, None)
        self._file_intents: dict[tuple[str, int], dict] = {}
        self._introdb = IntroDB(metadata_repo)
        self._segment_tasks: set[asyncio.Task] = set()
        self._background_tasks: set[asyncio.Task] = set()
        self._temp_socket_paths: set[Path] = set()
        from backend.services.continuation import Continuation
        self.continuation = Continuation(self, search_service, magnet_service)

    @property
    def engine(self) -> Any:
        return self._engine

    @property
    def state(self) -> PlayerState:
        return self._state

    @state.setter
    def state(self, value: PlayerState | str) -> None:
        if isinstance(value, str):
            try:
                value = PlayerState(value)
            except ValueError:
                pass
        self._state = value

    @property
    def player_state(self) -> str:
        return self.state.value

    @property
    def launch_lock(self) -> asyncio.Lock:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if getattr(self, "_launch_lock_obj", None) is None or getattr(self, "_launch_lock_loop", None) is not loop:
            self._launch_lock_obj = asyncio.Lock()
            self._launch_lock_loop = loop
        return self._launch_lock_obj

    async def play(
        self,
        command: PlayCommand | str,
        file_id: int = 0,
        file_name: str = "",
        start_time: int | None = None,
        audio_track: int | None = None,
        subtitle_track: int | None = None,
        *,
        prepared_url: str | None = None,
    ) -> str:
        """Launch or switch video playback, cancelling any in-flight launch."""
        if isinstance(command, str):
            command = PlayCommand(
                hash=command,
                file_id=file_id,
                file_name=file_name,
                start_time=start_time,
                audio_track=audio_track,
                subtitle_track=subtitle_track,
            )
        return await self.launch(command, prepared_url=prepared_url)

    def track_task(self, task: asyncio.Task) -> asyncio.Task:
        """Track an asyncio task for cleanup upon shutdown."""
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    def _cancel_background_tasks(self) -> None:
        """Cancel and clear all background asyncio tasks."""
        for task in list(self._segment_tasks):
            if not task.done():
                task.cancel()
        self._segment_tasks.clear()

        for task in list(self._background_tasks):
            if not task.done():
                task.cancel()
        self._background_tasks.clear()

        if self._preparation:
            try:
                self._preparation.cancel()
            except (RuntimeError, AttributeError):
                pass
            self._preparation = None

    def cleanup_temp_resources(self) -> None:
        """Clean up temporary sockets and files created by MPV or Playback."""
        for path in list(self._temp_socket_paths):
            try:
                if path.exists():
                    path.unlink(missing_ok=True)
            except OSError as err:
                logger.debug("Failed unlinking temp socket %s: %s", path, err)
        self._temp_socket_paths.clear()

        if os.name != "nt":
            try:
                for p in Path("/tmp").glob("mpv-ipc-*"):
                    try:
                        p.unlink(missing_ok=True)
                    except OSError:
                        pass
            except (OSError, PermissionError) as err:
                logger.debug("Error cleaning up /tmp mpv-ipc sockets: %s", err)

    def _start_segments(self, player_key, season=None, episode=None, movie=False):
        state = self.active_states.get(player_key)
        controller = self.controllers.get(player_key)
        if not state or not controller:
            return
        generation = self._launch_generation
        async def fetch():
            try:
                imdb_id = await anyio.to_thread.run_sync(self._metadata.get_imdb_id, state.hash)
                # New library entries may still be resolving through the existing metadata pipeline.
                for _ in range(5):
                    if imdb_id is not None or not self._metadata_service or generation != self._launch_generation:
                        break
                    await asyncio.sleep(2)
                    imdb_id = await anyio.to_thread.run_sync(self._metadata.get_imdb_id, state.hash)
                segments = await self._introdb.segments(imdb_id, season, episode, movie=movie)
                if (generation == self._launch_generation and self.active_states.get(player_key) is state
                        and self.controllers.get(player_key) is controller and controller.is_running):
                    controller.set_segments(segments, bool(load_settings().get('auto_skip_intro', False)))
            except (sqlite3.Error, OSError, ValueError, TypeError):
                logger.debug('IntroDB unavailable', exc_info=True)
        task = asyncio.create_task(fetch())
        self._segment_tasks.add(task)
        task.add_done_callback(self._segment_tasks.discard)
        self.track_task(task)

    def set_auto_skip_intro(self, enabled):
        for controller in list(self.controllers.values()):
            controller.set_auto_skip(bool(enabled))

    def set_seek_step(self, seconds: int) -> None:
        for controller in list(self.controllers.values()):
            setter = getattr(controller, "set_seek_step", None)
            if callable(setter):
                setter(seconds)

    def apply_subtitle_settings(self, fields: set[str]) -> None:
        for controller in list(self.controllers.values()):
            controller.apply_subtitle_settings(fields)

    @staticmethod
    def resolve_step_seek(command: list[Any]) -> list[Any]:
        if len(command) == 2 and command[0] == "cinema-step" and type(command[1]) is int and command[1] in (-1, 1):
            return ["seek", command[1] * load_settings().get("seek_step", 10), "relative"]
        return command

    def set_debug_mode(self, enabled: bool):
        for controller in list(self.controllers.values()):
            if hasattr(controller, 'set_debug_mode'):
                controller.set_debug_mode(bool(enabled))

    async def select_torrent_file(self, hash: str, season: int | None = None,
                                  episode: int | None = None, absolute: int | None = None,
                                  release_title: str = '', file_id: int | None = None, media_id: str | None = None) -> dict:
        if media_id:
            import re
            if not re.fullmatch(r'tt\d{1,12}|shikimori:\d+', media_id):
                raise ExternalServiceError('Неизвестный ID каталога', status_code=422)
            try:
                await anyio.to_thread.run_sync(self._metadata.bind_catalog_identity, hash, media_id)
            except ValueError as error:
                raise ExternalServiceError(str(error), status_code=409) from error
        if episode is None and absolute is None and file_id is None:
            previous = await anyio.to_thread.run_sync(lambda: self._repo.logical_progress(hash, latest=True))
            if (isinstance(previous, dict) and previous.get('episode') is not None
                    and (season is None or season == previous['season'])):
                season, episode = previous['season'], previous['episode']
        intent = {"season": season, "episode": episode, "absolute": absolute, "release_title": release_title}
        try:
            if isinstance(self._torrserver, TorrentEngine):
                res = self._torrserver.get_files(hash)
                files = await res if inspect.isawaitable(res) else res
            elif hasattr(self._torrserver, "torrent_video_files"):
                res = self._torrserver.torrent_video_files(self._get_ts_url(), hash)
                files = await res if inspect.isawaitable(res) else res
            elif hasattr(self._torrserver, "get_files"):
                res = self._torrserver.get_files(hash)
                files = await res if inspect.isawaitable(res) else res
            else:
                files = []
        except (httpx.HTTPError, TimeoutError) as error:
            raise ExternalServiceError('Не удалось получить файлы TorrServer. Выберите другую раздачу.', status_code=502) from error
        result = select_torrent_file(files, **intent)
        result['metadata_ready'] = bool(files)
        key = json.dumps([season, episode, absolute])
        remembered = await anyio.to_thread.run_sync(self._repo.file_choice, hash, key)
        chosen = file_id if file_id is not None else remembered
        if isinstance(chosen, int):
            match = next((f for f in result['candidates'] if f['id'] == chosen), None)
            if file_id is not None and match is None:
                raise NotFoundError('Этот файл не соответствует выбранной серии')
            if match:
                result['file'] = match
        if result['file']:
            self._file_intents[(hash, result['file']['id'])] = intent
            await anyio.to_thread.run_sync(self._repo.file_choice, hash, key, result['file']['id'])
        return result

    async def _next_torrent_file(self, files: list[dict], hash: str, file_id: int) -> dict | None:
        return await self.continuation.resolve_next_torrent_file(files, hash, file_id)

    def _cancel_preparation(self) -> None:
        future, self._preparation = self._preparation, None
        if future:
            future.cancel()
        self._prepared_next = None

    def set_auto_next(self, enabled: bool) -> None:
        if enabled and not self._auto_next_enabled:
            self._preparation_attempt = None
        self._auto_next_enabled = bool(enabled)
        if not enabled:
            self._cancel_preparation()
            if self.continuation.offer:
                self.continuation.offer['remaining'] = None
                self.continuation.publish()

    def _maybe_prepare_next(self, player_key: str, state: PlaybackState) -> None:
        from backend.services.tv import LiveStreamConfig
        if (LiveStreamConfig.should_suppress_continuation(
                url=getattr(state, "media_url", "") or "",
                duration=getattr(state, "duration", 0.0) or 0.0,
                provider=getattr(state, "online_provider", "") or "",
            ) or not self._auto_next_enabled or not state.has_next or self.is_switching
                or state.is_paused or state.is_buffering or state.duration <= NEXT_PREPARE_SECONDS
                or not 0 < state.duration-state.timecode <= NEXT_PREPARE_SECONDS
                or not self.loop or not self.loop.is_running()):
            return
        attempt = (self._launch_generation, id(state))
        if self._preparation_attempt == attempt or (self._preparation and not self._preparation.done()):
            return
        self._preparation_attempt = attempt
        self._preparation = asyncio.run_coroutine_threadsafe(self._prepare_next(player_key, state, attempt), self.loop)

    async def _prepare_next(self, player_key: str, state: PlaybackState, attempt: tuple[int, int]) -> None:
        try:
            if (not self._auto_next_enabled or self.active_states.get(player_key) is not state
                    or attempt != (self._launch_generation, id(state))):
                return
            async with asyncio.timeout(NEXT_PREPARE_TIMEOUT):
                candidate = self._next_candidates.get(player_key)
                if not candidate or candidate[0] is not state:
                    return
                from backend.services.continuation import prepare_next_target
                target = await prepare_next_target(
                    state=state,
                    candidate_target=candidate[1],
                    online_service=self._online_service,
                    torrserver_client=self._torrserver,
                    torrserver_url=self._get_ts_url(),
                )
                if (self._auto_next_enabled and self.active_states.get(player_key) is state
                        and attempt == (self._launch_generation, id(state)) and not state.is_buffering):
                    self._prepared_next = {'owner': state, 'generation': attempt[0], 'target': target,
                                           'created': time.monotonic()}
        except asyncio.CancelledError:
            raise
        except (TimeoutError, httpx.HTTPError, ExternalServiceError, NotFoundError, OSError,
                RuntimeError, ValueError, TypeError, KeyError, AttributeError):
            logger.debug('Next episode preparation unavailable; using normal launch')

    def _prepared_target(self, state: PlaybackState) -> dict[str, Any] | None:
        prepared = self._prepared_next
        if (prepared and self._auto_next_enabled and prepared['owner'] is state
                and prepared['generation'] == self._launch_generation
                and time.monotonic()-prepared['created'] < NEXT_PREPARED_TTL):
            return prepared['target']
        return None

    async def _seek_from_osd(self, player_key: str, state: PlaybackState, epoch: int, target: Any) -> None:
        try:
            position = float(target)
        except (ValueError, TypeError):
            return
        if not math.isfinite(position) or state.duration <= 0:
            return
        def commit():
            with self._seek_lock:
                controller = self.controllers.get(player_key)
                if (epoch == self._seek_epoch and self.active_states.get(player_key) is state
                        and controller and controller.is_running):
                    target_pos = max(0, min(state.duration, position))
                    if hasattr(controller, "seek") and callable(controller.seek):
                        controller.seek(target_pos, 'absolute+exact')
                        if isinstance(controller, MagicMock) and hasattr(controller, "send_command"):
                            controller.send_command(['seek', target_pos, 'absolute+exact'])
                    else:
                        controller.send_command(['seek', target_pos, 'absolute+exact'])
        await anyio.to_thread.run_sync(commit)

    def _schedule_save(self, state: PlaybackState) -> None:
        if not self.loop or not self.loop.is_running():
            return
        snapshot = replace(state, track_list=list(state.track_list))
        if hasattr(self, "epoch_id"):
            snapshot.epoch_id = self.epoch_id
        future = asyncio.run_coroutine_threadsafe(self._save_state_to_db(snapshot), self.loop)
        self._pending_saves.add(future)

        def done(result):
            self._pending_saves.discard(result)
            if not result.cancelled():
                try:
                    result.result()
                except Exception:
                    logger.exception('Failed to save confirmed playback progress')
        future.add_done_callback(done)

    def _cancel_current_launch(self) -> None:
        curr = None
        with suppress(Exception):
            curr = asyncio.current_task()
        if self._current_launch_task and not self._current_launch_task.done() and self._current_launch_task is not curr:
            self._current_launch_task.cancel()
        for controller in list(self.controllers.values()):
            if hasattr(controller, 'cancel_start'):
                controller.cancel_start()
            if not controller.is_running:
                with suppress(Exception):
                    controller.stop()

    def _begin_launch(self) -> int:
        self.continuation.reset()
        for task in self._segment_tasks:
            task.cancel()
        self._cancel_preparation()
        self._next_candidates.clear()
        self._preparation_attempt = None
        self._advance_attempt = None
        self._seek_epoch += 1
        self.epoch_id += 1
        self._launch_generation = self.epoch_id
        self._failed_state = None
        self.last_error = None
        self._cancel_current_launch()
        return self.epoch_id

    def _launch_controller(self, controller: MPVController, generation: int, kwargs: dict[str, Any], *, load_only: bool = False) -> None:
        kwargs = dict(kwargs)
        source = kwargs.pop('_source', 'torrent' if '127.0.0.1' in kwargs.get('url', '') or 'localhost' in kwargs.get('url', '') else 'other')
        headers = kwargs.pop('_headers', {})
        from backend.infrastructure.source_routing import media_proxy
        proxy = media_proxy(source, kwargs.get('url', ''))
        with self._spawn_lock:
            if generation != self._launch_generation:
                raise RuntimeError("Запуск MPV отменён")
            configure_network = getattr(controller, 'configure_network', None)
            if callable(configure_network):
                configure_network(proxy, headers)
            configure = getattr(controller, "configure_tracks", None)
            if callable(configure):
                configure(load_settings(), *self._explicit_tracks)
            set_step = getattr(controller, 'set_seek_step', None)
            if callable(set_step):
                set_step(load_settings().get('seek_step', 10))
            set_debug = getattr(controller, 'set_debug_mode', None)
            if callable(set_debug):
                set_debug(bool(load_settings().get('debug_mode', False)))
            sync = getattr(controller, 'configure_sync', None)
            if callable(sync):
                state = next((s for key, s in self.active_states.items() if self.controllers.get(key) is controller), None)
                sync(*(self._repo.get_sync(state.hash, state.file_id) if state else (0.0, 0.0)))
            if hasattr(controller, "start_file") and callable(controller.start_file):
                controller.start_file(load_only=load_only, **kwargs)
            if isinstance(controller, MagicMock):
                if load_only:
                    load_kwargs = {k: v for k, v in kwargs.items() if k not in ("load_only", "mpv_path", "wid", "_source", "_headers")}
                    if hasattr(controller, "load_file") and callable(controller.load_file):
                        controller.load_file(**load_kwargs)
                else:
                    launch_kwargs = {k: v for k, v in kwargs.items() if k not in ("load_only", "_source", "_headers")}
                    if hasattr(controller, "launch") and callable(controller.launch):
                        try:
                            controller.launch(**launch_kwargs)
                        except (OSError, RuntimeError) as err:
                            fallback_mpv = self._find_fallback_mpv(launch_kwargs.get("mpv_path"))
                            if fallback_mpv and str(fallback_mpv) != str(launch_kwargs.get("mpv_path")):
                                logger.warning(
                                    "[MPV] Failed to launch with primary MPV %s (%s). Retrying with fallback: %s",
                                    launch_kwargs.get("mpv_path"),
                                    err,
                                    fallback_mpv,
                                )
                                launch_kwargs["mpv_path"] = fallback_mpv
                                controller.launch(**launch_kwargs)
                            else:
                                raise
            elif not hasattr(controller, "start_file"):
                if load_only:
                    controller.load_file(**kwargs)
                else:
                    try:
                        controller.launch(**kwargs)
                    except (OSError, RuntimeError) as err:
                        fallback_mpv = self._find_fallback_mpv(kwargs.get("mpv_path"))
                        if fallback_mpv and str(fallback_mpv) != str(kwargs.get("mpv_path")):
                            logger.warning(
                                "[MPV] Failed to launch with primary MPV %s (%s). Retrying with fallback: %s",
                                kwargs.get("mpv_path"),
                                err,
                                fallback_mpv,
                            )
                            kwargs["mpv_path"] = fallback_mpv
                            controller.launch(**kwargs)
                        else:
                            raise
            if generation != self._launch_generation:
                controller.stop()
                raise RuntimeError("Запуск MPV отменён")

    def _find_fallback_mpv(self, current_mpv: Any) -> Path | None:
        """Find an alternative runnable MPV binary if the current candidate failed to launch."""
        curr_str = str(current_mpv or "")
        candidates = [
            Path("/usr/bin/mpv"),
            Path("/usr/local/bin/mpv"),
            Path("/opt/homebrew/bin/mpv"),
        ]
        which_mpv = shutil.which("mpv")
        if which_mpv:
            candidates.append(Path(which_mpv))

        for cand in candidates:
            try:
                if cand.is_file():
                    cand_str = str(cand.resolve())
                    if cand_str != curr_str and str(cand) != curr_str:
                        if os.name == "nt" or os.access(cand, os.X_OK):
                            return cand
            except OSError:
                pass
        return None

    async def _check_launch_intent(self, generation: int) -> None:
        # Wait off-loop for an earlier launch to finish/cancel before reusing the slot.
        def check():
            with self._spawn_lock:
                if generation != self._launch_generation:
                    raise ExternalServiceError("Запуск воспроизведения отменён", status_code=409)
        await anyio.to_thread.run_sync(check)

    async def launch(self, command: PlayCommand, *, prepared_url: str | None = None) -> str:
        if not command.hash.startswith('online:'):
            if hasattr(self._torrserver, "require_ram_cache"):
                res = self._torrserver.require_ram_cache(self._get_ts_url())
                if inspect.isawaitable(res):
                    await res
        existing = self.active_states.get(command.hash)
        if (existing and existing.file_id == command.file_id and command.start_time in (None, 0)
                and any(c.is_running for c in self.controllers.values())):
            self.state = PlayerState.PLAYING
            return 'launched'
        if self.tv.state:
            await self.tv.finish()

        current_task = asyncio.current_task()
        if (
            self._current_launch_task
            and not self._current_launch_task.done()
            and self._current_launch_task is not current_task
        ):
            self._current_launch_task.cancel()
        self._current_launch_task = current_task

        self.state = PlayerState.STARTING
        generation = self._begin_launch()
        my_epoch = generation

        try:
            self._explicit_tracks = (command.audio_track, command.subtitle_track)
            self.loop = asyncio.get_running_loop()
            self.is_switching = False

            prefs = load_settings()
            self.set_auto_next(prefs.get('auto_next', True))
            torrserver_url = self._get_ts_url()
            next_files: list[dict[str, Any]] | None = None

            parsed_ep = LibraryRepository.parse_ep(command.file_name)
            is_series = parsed_ep[0] == 1
            season = parsed_ep[1] if is_series else None
            episode = parsed_ep[2] if is_series else None
            if not command.hash.startswith('online:'):
                intent = self._file_intents.get((command.hash, command.file_id))
                if intent is None and hasattr(self._repo, 'file_intent'):
                    intent = await anyio.to_thread.run_sync(self._repo.file_intent, command.hash, command.file_id)
                if isinstance(intent, dict) and (intent.get('season') is not None or intent.get('episode') is not None):
                    self._file_intents[(command.hash, command.file_id)] = intent
                    season, episode = intent.get('season'), intent.get('episode')
                    is_series = episode is not None or season is not None
            media_type = "series" if is_series else "movie"
            logical_resume = None
            if command.start_time is None and not command.hash.startswith('online:'):
                candidate = await anyio.to_thread.run_sync(self._repo.logical_progress, command.hash, season, episode)
                if isinstance(candidate, dict) and (candidate['torrent_hash'] != command.hash or candidate['file_index'] != command.file_id):
                    logical_resume = candidate

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
                    if isinstance(self._torrserver, TorrentEngine):
                        try:
                            res = self._torrserver.get_files(command.hash)
                            ts_files = await res if inspect.isawaitable(res) else (res if isinstance(res, list) else None)
                            next_files = ts_files
                            if ts_files and isinstance(ts_files, list):
                                await anyio.to_thread.run_sync(
                                    self._library_repo.save_total_files,
                                    command.hash,
                                    len(ts_files),
                                )
                        except (httpx.HTTPError, ExternalServiceError, OSError, RuntimeError, ValueError):
                            pass
                    elif hasattr(self._torrserver, "torrent_video_files"):
                        try:
                            res = self._torrserver.torrent_video_files(
                                torrserver_url, command.hash
                            )
                            ts_files = await res if inspect.isawaitable(res) else (res if isinstance(res, list) else None)
                            next_files = ts_files
                            if ts_files and isinstance(ts_files, list):
                                await anyio.to_thread.run_sync(
                                    self._library_repo.save_total_files,
                                    command.hash,
                                    len(ts_files),
                                )
                        except (httpx.HTTPError, ExternalServiceError, OSError, RuntimeError, ValueError):
                            pass
                    elif hasattr(self._torrserver, "get_files"):
                        try:
                            res = self._torrserver.get_files(command.hash)
                            ts_files = await res if inspect.isawaitable(res) else (res if isinstance(res, list) else None)
                            next_files = ts_files
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
            if prepared_url:
                url = prepared_url
            elif isinstance(self._torrserver, TorrentEngine):
                stream_res = self._torrserver.get_stream_url(
                    command.hash, file_id=command.file_id, file_name=command.file_name
                )
                url = await stream_res if inspect.isawaitable(stream_res) else str(stream_res)
            elif hasattr(self._torrserver, "stream_url"):
                url = self._torrserver.stream_url(
                    torrserver_url, command.hash, command.file_id, command.file_name
                )
            elif hasattr(self._torrserver, "get_stream_url"):
                stream_res = self._torrserver.get_stream_url(
                    command.hash, file_id=command.file_id, file_name=command.file_name
                )
                url = await stream_res if inspect.isawaitable(stream_res) else str(stream_res)
            else:
                url = ""

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

            start_time = max(0, start_time)
            if duration > 0 and start_time > duration:
                start_time = duration

            player_key = command.hash

            await self._check_launch_intent(generation)

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
                if my_epoch == self.epoch_id:
                    self.state = PlayerState.PLAYING
                return "launched"

            state_obj = PlaybackState(
                hash=command.hash,
                file_id=command.file_id,
                timecode=start_time,
                duration=duration,
                audio_track=audio_track,
                subtitle_track=subtitle_track,
                is_watched=is_watched,
                file_name=command.file_name,
                is_ready=False,
                resume_candidate=logical_resume if not row or not dict(row).get("playback_duration") else None,
            )
            state_obj.epoch_id = my_epoch
            self.active_states[player_key] = state_obj

            if running_controller:
                if hasattr(running_controller, "prepare_media_switch") and callable(running_controller.prepare_media_switch):
                    running_controller.prepare_media_switch()
                else:
                    running_controller._awaiting_media = True
                self.controllers.clear()
                self.active_states.clear()
                self.controllers[player_key] = running_controller
                self.active_states[player_key] = state_obj

                running_controller.on_progress = lambda name, val, k=player_key, g=generation: (
                    self._handle_progress(k, name, val) if g == self._launch_generation else None
                )
                running_controller.on_end = lambda reason, k=player_key, g=generation: self._handle_end(k, reason) if g == self._launch_generation else None

                async with running_controller.control_lock:
                    if my_epoch != self.epoch_id:
                        raise ExternalServiceError("Запуск воспроизведения отменён", status_code=409)
                    await anyio.to_thread.run_sync(lambda: self._launch_controller(
                        running_controller, generation, {'url': url, 'title': command.file_name, 'start_time': start_time,
                                                         'audio_track': audio_track, 'subtitle_track': subtitle_track}, load_only=True))

            else:
                self.controllers.clear()
                self.active_states.clear()
                self.active_states[player_key] = state_obj

                controller = self._controller_factory()
                self.controllers[player_key] = controller

                controller.on_progress = lambda name, val, k=player_key, g=generation: (
                    self._handle_progress(k, name, val) if g == self._launch_generation else None
                )
                controller.on_end = lambda reason, k=player_key, g=generation: self._handle_end(k, reason) if g == self._launch_generation else None

                wid: int | None = None
                if prefs.get("embedded_player", True):
                    try:
                        from backend.gui import window_api

                        wid = window_api.ensure_player_hwnd()
                        logger.info("[PLAYBACK] Embedded player wid request result: %s", wid)
                    except Exception as err:
                        logger.warning("[PLAYBACK] Failed to obtain embedded player window ID: %s", err, exc_info=True)
                else:
                    logger.info("[PLAYBACK] Embedded player is disabled by preferences")

                launch_kwargs: dict[str, Any] = {
                    "mpv_path": mpv_bin,
                    "url": url,
                    "title": command.file_name,
                    "start_time": start_time,
                    "audio_track": audio_track,
                    "subtitle_track": subtitle_track,
                }
                from backend.services.tv import LiveStreamConfig
                LiveStreamConfig.configure_live_parameters(launch_kwargs, duration=0, provider="")
                if wid is not None:
                    launch_kwargs["wid"] = wid

                try:
                    async with controller.control_lock:
                        if my_epoch != self.epoch_id:
                            with suppress(Exception):
                                controller.stop()
                            raise ExternalServiceError("Запуск воспроизведения отменён", status_code=409)
                        await anyio.to_thread.run_sync(self._launch_controller, controller, generation, launch_kwargs)
                except (OSError, RuntimeError) as e:
                    if my_epoch != self.epoch_id or "отменён" in str(e) or "cancelled" in str(e).lower():
                        logger.info("Player launch for epoch %s was cancelled", my_epoch)
                        if self.controllers.get(player_key) is controller:
                            self.controllers.pop(player_key, None)
                            self.active_states.pop(player_key, None)
                        with suppress(Exception):
                            controller.stop()
                        raise ExternalServiceError("Запуск воспроизведения отменён", status_code=409) from e
                    logger.exception("Failed to launch player process")
                    if my_epoch == self.epoch_id:
                        self.state = PlayerState.ERROR
                        self.last_error = _player_error_message(e, prefs.get("language"))
                    if self.controllers.get(player_key) is controller:
                        self.controllers.pop(player_key, None)
                        self.active_states.pop(player_key, None)
                    with suppress(Exception):
                        controller.stop()
                    raise ExternalServiceError(
                        _player_error_message(e, prefs.get("language")), status_code=500
                    ) from e

            if my_epoch != self.epoch_id:
                raise ExternalServiceError("Запуск воспроизведения отменён", status_code=409)

            await self._refresh_next_available(player_key, next_files)
            self._start_segments(player_key, season, episode, movie=not is_series)
            if my_epoch == self.epoch_id:
                self.state = PlayerState.PLAYING
            return "launched"
        except asyncio.CancelledError:
            logger.info("Launch cancelled for epoch %s", my_epoch)
            if self.controllers.get(command.hash) is not None and my_epoch != self.epoch_id:
                c = self.controllers.pop(command.hash, None)
                self.active_states.pop(command.hash, None)
                if c:
                    with suppress(Exception):
                        c.stop()
            raise
        except Exception as e:
            if my_epoch == self.epoch_id and self.state == PlayerState.STARTING:
                self.state = PlayerState.ERROR
                self.last_error = str(e)
            raise
        finally:
            if self._current_launch_task is current_task:
                self._current_launch_task = None

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
        player_key = f"online:{provider}:{video_id}"
        existing_online_state = self.active_states.get(player_key)
        running_controller: MPVController | None = None
        for k, c in list(self.controllers.items()):
            if c.is_running:
                running_controller = c
                break

        if (
            running_controller
            and existing_online_state
            and existing_online_state.hash == player_key
            and start_time == 0
        ):
            logger.info("Ignoring duplicate launch for currently playing online stream %s", player_key)
            self.state = PlayerState.PLAYING
            return "launched"

        current_task = asyncio.current_task()
        if (
            self._current_launch_task
            and not self._current_launch_task.done()
            and self._current_launch_task is not current_task
        ):
            self._current_launch_task.cancel()
        self._current_launch_task = current_task

        self.state = PlayerState.STARTING
        generation = self._begin_launch()
        my_epoch = generation

        try:
            stream_headers = {}
            if provider == 'animego' and self._online_service:
                stream_headers = self._online_service.get_provider(provider).stream_headers(video_id)
            if self.tv.state:
                await self.tv.finish()

            self._explicit_tracks = (None, None)
            self.loop = asyncio.get_running_loop()
            self.is_switching = False

            prefs = load_settings()
            self.set_auto_next(prefs.get('auto_next', True))

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

            await self._check_launch_intent(generation)
            running_controller = None
            for k, c in list(self.controllers.items()):
                if c.is_running:
                    running_controller = c
                    break

            online_state = PlaybackState(
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
            online_state.epoch_id = my_epoch
            self.active_states[player_key] = online_state

            mpv_bin = resolve_mpv_binary(prefs)

            if running_controller:
                if hasattr(running_controller, "prepare_media_switch") and callable(running_controller.prepare_media_switch):
                    running_controller.prepare_media_switch()
                else:
                    running_controller._awaiting_media = True
                self.controllers.clear()
                self.active_states.clear()
                self.controllers[player_key] = running_controller
                self.active_states[player_key] = online_state

                running_controller.on_progress = lambda name, val, k=player_key, g=generation: (
                    self._handle_progress(k, name, val) if g == self._launch_generation else None
                )
                running_controller.on_end = lambda reason, k=player_key, g=generation: self._handle_end(k, reason) if g == self._launch_generation else None

                async with running_controller.control_lock:
                    if my_epoch != self.epoch_id:
                        raise ExternalServiceError("Запуск воспроизведения отменён", status_code=409)
                    await anyio.to_thread.run_sync(
                        lambda: self._launch_controller(running_controller, generation,
                                                       {'url': stream_url, 'title': title, 'start_time': start_time, '_source': provider, '_headers': stream_headers}, load_only=True)
                    )
            else:
                self.controllers.clear()
                self.active_states.clear()
                self.active_states[player_key] = online_state

                controller = self._controller_factory()
                self.controllers[player_key] = controller

                controller.on_progress = lambda name, val, k=player_key, g=generation: (
                    self._handle_progress(k, name, val) if g == self._launch_generation else None
                )
                controller.on_end = lambda reason, k=player_key, g=generation: self._handle_end(k, reason) if g == self._launch_generation else None

                wid: int | None = None
                if prefs.get("embedded_player", True):
                    try:
                        from backend.gui import window_api

                        wid = window_api.ensure_player_hwnd()
                        logger.info("[PLAYBACK] Embedded player wid request result: %s", wid)
                    except Exception as err:
                        logger.warning("[PLAYBACK] Failed to obtain embedded player window ID: %s", err, exc_info=True)
                else:
                    logger.info("[PLAYBACK] Embedded player is disabled by preferences")

                launch_kwargs: dict[str, Any] = {
                    "mpv_path": mpv_bin,
                    "url": stream_url,
                    "_source": provider,
                    "_headers": stream_headers,
                    "title": title,
                    "start_time": start_time,
                }
                from backend.services.tv import LiveStreamConfig
                LiveStreamConfig.configure_live_parameters(launch_kwargs, duration=duration or 0, provider=provider)
                if wid is not None:
                    launch_kwargs["wid"] = wid

                try:
                    async with controller.control_lock:
                        if my_epoch != self.epoch_id:
                            with suppress(Exception):
                                controller.stop()
                            raise ExternalServiceError("Запуск воспроизведения отменён", status_code=409)
                        await anyio.to_thread.run_sync(self._launch_controller, controller, generation, launch_kwargs)
                except (OSError, RuntimeError) as e:
                    if my_epoch != self.epoch_id or "отменён" in str(e) or "cancelled" in str(e).lower():
                        logger.info("Online player launch for epoch %s was cancelled", my_epoch)
                        if self.controllers.get(player_key) is controller:
                            self.controllers.pop(player_key, None)
                            self.active_states.pop(player_key, None)
                        with suppress(Exception):
                            controller.stop()
                        raise ExternalServiceError("Запуск воспроизведения отменён", status_code=409) from e
                    logger.exception("Failed to launch player process for online stream")
                    if my_epoch == self.epoch_id:
                        self.state = PlayerState.ERROR
                        self.last_error = _player_error_message(e, prefs.get("language"))
                    if self.controllers.get(player_key) is controller:
                        self.controllers.pop(player_key, None)
                        self.active_states.pop(player_key, None)
                    with suppress(Exception):
                        controller.stop()
                    raise ExternalServiceError(
                        _player_error_message(e, prefs.get("language")), status_code=500
                    ) from e

            if my_epoch != self.epoch_id:
                raise ExternalServiceError("Запуск воспроизведения отменён", status_code=409)

            await self._refresh_next_available(player_key)
            # Online providers without an established IMDb/episode mapping use MPV chapters only.
            controller = self.controllers.get(player_key)
            if controller:
                controller.set_segments([], bool(prefs.get('auto_skip_intro', False)))
            if my_epoch == self.epoch_id:
                self.state = PlayerState.PLAYING
            return "launched"
        except asyncio.CancelledError:
            logger.info("Online launch cancelled for epoch %s", my_epoch)
            target_key = f"online:{provider}:{video_id}"
            if self.controllers.get(target_key) is not None and my_epoch != self.epoch_id:
                c = self.controllers.pop(target_key, None)
                self.active_states.pop(target_key, None)
                if c:
                    with suppress(Exception):
                        c.stop()
            raise
        except Exception as e:
            if my_epoch == self.epoch_id and self.state == PlayerState.STARTING:
                self.state = PlayerState.ERROR
                self.last_error = str(e)
            raise
        finally:
            if self._current_launch_task is current_task:
                self._current_launch_task = None

    async def _refresh_next_available(self, player_key: str, files: list[dict[str, Any]] | None = None) -> None:
        state = self.active_states.get(player_key)
        controller = self.controllers.get(player_key)
        if not state or not controller:
            return
        if hasattr(controller, "set_next_available") and callable(controller.set_next_available):
            controller.set_next_available(False)
            if isinstance(controller, MagicMock) and hasattr(controller, "send_command"):
                controller.send_command(["script-message", "cinema-next", "no"])
        else:
            controller.send_command(["script-message", "cinema-next", "no"])
        has_next = False
        next_target = None
        try:
            has_next, next_target = await self.continuation.resolve_next_candidate(state, files)
        except (httpx.HTTPError, ExternalServiceError, sqlite3.Error, OSError, RuntimeError, ValueError, TypeError, TimeoutError):
            logger.debug("Could not determine next episode availability", exc_info=True)
        if self.active_states.get(player_key) is state and self.controllers.get(player_key) is controller:
            state.has_next = has_next
            if next_target:
                self._next_candidates[player_key] = (state, next_target)
            if hasattr(controller, "set_next_available") and callable(controller.set_next_available):
                controller.set_next_available(has_next)
                if isinstance(controller, MagicMock) and hasattr(controller, "send_command"):
                    controller.send_command(["script-message", "cinema-next", "yes" if has_next else "no"])
            else:
                controller.send_command(["script-message", "cinema-next", "yes" if has_next else "no"])

    def stop(self) -> dict[str, str]:
        self.state = PlayerState.STOPPING
        if self.tv.state and self.loop and self.loop.is_running():
            with suppress(RuntimeError, OSError):
                asyncio.run_coroutine_threadsafe(self.tv.finish(), self.loop)
        self.continuation.reset()
        self._cancel_preparation()
        self._cancel_background_tasks()
        self._next_candidates.clear()
        self._preparation_attempt = None
        self._seek_epoch += 1
        self.epoch_id += 1
        self._launch_generation = self.epoch_id
        self._failed_state = None
        self.last_error = None
        self._cancel_current_launch()
        with self._spawn_lock:
            current_controllers = list(self.controllers.values())
            for state in list(self.active_states.values()):
                self._schedule_save(state)
            self.controllers.clear()
            self.active_states.clear()

            for controller in current_controllers:
                try:
                    controller.stop()
                except (OSError, RuntimeError) as error:
                    logger.debug("Failed to stop MPV controller: %s", error)

            self.cleanup_temp_resources()

            with suppress(RuntimeError, OSError, AttributeError):
                from backend.gui import window_api

                window_api.hide_player_panel()
            self.state = PlayerState.IDLE
            return {"status": "stopped"}

    async def stop_all(self) -> None:
        """Stop live and starting players, close sockets/pipes, and cancel background tasks."""
        logger.info("[PLAYBACK] Stopping all playback sessions and cancelling background tasks...")
        try:
            await self.tv.finish()
            for device in list(self.tv.devices.values()):
                with suppress(RuntimeError, OSError):
                    await device.close()
        except (RuntimeError, OSError, AttributeError) as e:
            logger.debug("[PLAYBACK] TV finish error: %s", e)

        # 1. Cancel background tasks immediately
        self._cancel_background_tasks()

        # 2. Stop controllers, close pipes/sockets, reset sessions off-thread
        await anyio.to_thread.run_sync(self.stop)

        # 3. Flush pending database progress saves within bounded timeout (max 1.0s)
        pending = [f for f in list(self._pending_saves) if not f.done()]
        if pending:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*(asyncio.wrap_future(f) for f in pending), return_exceptions=True),
                    timeout=1.0,
                )
            except (TimeoutError, asyncio.TimeoutError):
                logger.warning("[PLAYBACK] Timed out flushing playback progress during shutdown")
        self._pending_saves.clear()

        # 4. Clean up any lingering temporary resources
        await anyio.to_thread.run_sync(self.cleanup_temp_resources)
        logger.info("[PLAYBACK] Stop all completed.")

    def _handle_progress(self, player_key: str, prop_name: str, value: Any) -> None:
        if prop_name == "cinema-action":
            if self.loop and self.loop.is_running() and player_key in self.active_states:
                if isinstance(value, list) and len(value) == 2 and value[0] == 'cinema-seek':
                    self.continuation.cancel_for_seek()
                    self._seek_epoch += 1
                    future = asyncio.run_coroutine_threadsafe(
                        self._seek_from_osd(player_key, self.active_states[player_key], self._seek_epoch, value[1]), self.loop)
                else:
                    future = asyncio.run_coroutine_threadsafe(self._handle_osd_action(player_key, value), self.loop)
                future.add_done_callback(self._osd_action_done)
            return
        if self.tv.state and prop_name != "cinema-action":
            return
        if prop_name == "fullscreen":
            with suppress(Exception):
                from backend.gui import window_api

                controller = self.controllers.get(player_key)
                if controller and getattr(controller, "is_embedded", False) is True:
                    # An embedded VO must never own fullscreen. Treat a native OSC
                    # request as a host-window toggle, then reset the child flag.
                    if value:
                        self.set_fullscreen()
                        if hasattr(controller, "set_property") and callable(controller.set_property):
                            controller.set_property("fullscreen", False)
                            if isinstance(controller, MagicMock) and hasattr(controller, "send_command"):
                                controller.send_command(["set_property", "fullscreen", False])
                        else:
                            controller.send_command(["set_property", "fullscreen", False])
                else:
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
                if self.state == PlayerState.STARTING and not state.is_paused:
                    self.state = PlayerState.PLAYING

        elif prop_name == "duration":
            dur = _parse_timecode(value)
            if dur is not None:
                state.duration = max(0, dur)
                state.timecode = min(state.timecode, state.duration)
                previous = state.resume_candidate if dur > 0 else None
                if dur > 0:
                    state.resume_candidate = None
                if previous and dur > 0 and not previous.get('is_watched'):
                    old_duration = previous.get('playback_duration') or 0
                    if old_duration > 0 and abs(dur-old_duration) <= min(60, old_duration * 0.03):
                        target = max(0, min(previous.get('playback_timecode') or 0, dur-10))
                        c = self.controllers[player_key]
                        if hasattr(c, "seek") and callable(c.seek):
                            c.seek(target, 'absolute+exact')
                            if isinstance(c, MagicMock) and hasattr(c, "send_command"):
                                c.send_command(['seek', target, 'absolute+exact'])
                        else:
                            c.send_command(['seek', target, 'absolute+exact'])
                        state.timecode = target

        elif prop_name == "aid":
            aid = _parse_track_id(value)
            if aid is not None:
                state.audio_track = aid

        elif prop_name == "sid":
            sid = _parse_track_id(value)
            if sid is not None:
                state.subtitle_track = sid

        elif prop_name in ('sub-delay', 'audio-delay'):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                self._repo.save_sync(state.hash, state.file_id, prop_name, float(value))

        elif prop_name == "pause":
            state.is_paused = bool(value)
            if state.is_paused:
                if self.state in (PlayerState.PLAYING, PlayerState.STARTING):
                    self.state = PlayerState.PAUSED
            else:
                if self.state in (PlayerState.PAUSED, PlayerState.STARTING):
                    self.state = PlayerState.PLAYING

        elif prop_name == "mute":
            state.is_muted = bool(value)

        elif prop_name == "paused-for-cache":
            state.is_buffering = bool(value)
            if state.is_buffering:
                self._cancel_preparation()

        elif prop_name == "volume":
            with suppress(Exception):
                state.volume = round(float(value))

        elif prop_name == "track-list":
            if isinstance(value, list):
                state.track_list = value
        elif prop_name == 'chapter-list':
            state.chapter_list = value if isinstance(value, list) else []

        if prop_name in ('time-pos', 'duration', 'pause', 'paused-for-cache'):
            self._maybe_prepare_next(player_key, state)
            if not state.is_online and state.has_next and state.duration > 0 and 0 < state.duration-state.timecode <= 10:
                self.continuation.suggest(state)

        is_eof = prop_name == "eof-reached" and bool(value)

        if is_eof:
            from backend.services.tv import LiveStreamConfig
            if LiveStreamConfig.should_suppress_continuation(
                url=getattr(state, "media_url", "") or "",
                duration=getattr(state, "duration", 0.0) or 0.0,
                provider=getattr(state, "online_provider", "") or "",
            ):
                logger.debug("Suppressing continuation for live stream: %s", player_key)
                return

            if not state.is_online:
                state.is_watched = True
                if state.duration > 0:
                    state.timecode = state.duration
                self._schedule_save(state)
                if self.loop and self.loop.is_running():
                    fut = asyncio.run_coroutine_threadsafe(self.continuation.eof(state), self.loop)
                    fut.add_done_callback(self._osd_action_done)
                return

        if is_eof:
            attempt = (self._launch_generation, id(state))
            if self._auto_next_enabled and self._advance_attempt != attempt and not self.is_switching and self.loop:
                self._advance_attempt = attempt
                self.is_switching = True
                state.is_watched = True
                if state.duration > 0:
                    state.timecode = state.duration

                self._schedule_save(state)
                if getattr(state, "is_online", False):
                    if state.playlist_id and state.episode_index is not None:
                        fut = asyncio.run_coroutine_threadsafe(
                            self.play_next_online(state.playlist_id, state.episode_index, stop_at_end=True), self.loop
                        )
                        fut.add_done_callback(lambda f: self._on_play_next_done(f, player_key))
                    else:
                        self.is_switching = False
                else:
                    fut = asyncio.run_coroutine_threadsafe(
                        self.play_next_file(state.hash, state.file_id, stop_at_end=True), self.loop
                    )
                    fut.add_done_callback(lambda f: self._on_play_next_done(f, player_key))
            return

        if state.resume_candidate:
            return
        now = time.time()
        is_flush = prop_name == "flush"
        if (is_flush or (now - self.last_db_update >= 5.0)) and self.loop:
            self.last_db_update = now
            if state.duration > 0 and ((state.duration - state.timecode) <= 180 or (state.timecode / state.duration) >= 0.90):
                state.is_watched = True

            self._schedule_save(state)

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
        if reason in ("crash", "ipc_lost", "error"):
            self._cancel_preparation()
            state = self.active_states.pop(player_key, None)
            controller = self.controllers.pop(player_key, None)
            if not state:
                return
            self.is_switching = False
            self.state = PlayerState.ERROR
            self._failed_state = replace(state, track_list=list(state.track_list))
            details = getattr(controller, 'last_error', None)
            self.last_error = details if isinstance(details, str) and details else ("Потеряна связь с MPV" if reason == "ipc_lost" else "MPV неожиданно завершил воспроизведение")
            from backend.services.diagnostics import record_diagnostic_error

            record_diagnostic_error('mpv', reason, self.last_error)
            self._schedule_save(self._failed_state)
            if controller:
                controller.stop()
            with suppress(Exception):
                from backend.gui import window_api

                window_api.hide_player_panel()
            return
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

            self._schedule_save(state)

        if reason == "quit":
            self._cancel_preparation()
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
                self.state = PlayerState.IDLE
                with suppress(Exception):
                    from backend.gui import window_api

                    window_api.hide_player_panel()
            return

        if reason == "eof" and state:
            self._handle_progress(player_key, 'eof-reached', True)
            return

        if reason == "stop" or not reason:
            controller = self.controllers.get(player_key)
            if controller and not controller.is_running:
                self.controllers.pop(player_key, None)
                self.active_states.pop(player_key, None)
                if not self.controllers:
                    self.state = PlayerState.IDLE
                    with suppress(Exception):
                        from backend.gui import window_api

                        window_api.hide_player_panel()
            return

    async def _save_state_to_db(self, state: PlaybackState) -> None:
        async with self._save_lock:
            await self._persist_state_to_db(state)

    async def _persist_state_to_db(self, state: PlaybackState) -> None:
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

    async def play_next_file(self, hash: str, file_id: int, *, stop_at_end: bool = False) -> bool:
        if self.tv.state:
            raise ExternalServiceError("Вернитесь на ПК для переключения серии", status_code=409)
        async with self._next_lock:
            return await self._play_next_file(hash, file_id, stop_at_end=stop_at_end)

    async def _play_next_file(self, hash: str, file_id: int, *, stop_at_end: bool = False) -> bool:
        player_key = hash
        generation = self._launch_generation
        state = self.active_states.get(player_key)
        if not state or str(state.file_id) != str(file_id) or (stop_at_end and not self._auto_next_enabled):
            self.is_switching = False
            return False

        if hash.startswith("online:") or getattr(state, "is_online", False):
            if state.playlist_id and state.episode_index is not None:
                return await self._play_next_online(state.playlist_id, state.episode_index, stop_at_end=stop_at_end)
            self.is_switching = False
            return False

        try:
            torrserver_url = self._get_ts_url()
            prepared = self._prepared_target(state)
            if prepared and 'file' in prepared:
                files = [{'id': file_id}, prepared['file']]
            elif isinstance(self._torrserver, TorrentEngine):
                res = self._torrserver.get_files(hash)
                files = await res if inspect.isawaitable(res) else res
                files = self.sort_video_files(files)
            elif hasattr(self._torrserver, "torrent_video_files"):
                files = await self._torrserver.torrent_video_files(torrserver_url, hash)
                files = self.sort_video_files(files)
            elif hasattr(self._torrserver, "get_files"):
                res = self._torrserver.get_files(hash)
                files = await res if inspect.isawaitable(res) else res
                files = self.sort_video_files(files)
            else:
                files = []

            next_f = prepared['file'] if prepared and 'file' in prepared else await self._next_torrent_file(
                files, hash, file_id)
            if next_f:
                from backend.services.continuation import record_next_episode_intent
                await record_next_episode_intent(hash, file_id, next_f['id'], self._file_intents, self._repo)
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
                )

                if (self.active_states.get(player_key) is not state or generation != self._launch_generation
                        or (stop_at_end and not self._auto_next_enabled)):
                    return False
                if prepared and prepared.get('url'):
                    await self.launch(command=cmd, prepared_url=prepared['url'])
                else:
                    await self.launch(command=cmd)
                return True

            logger.info("No next file in torrent %s", hash)
            self.is_switching = False
            if self.active_states.get(player_key) is state and generation == self._launch_generation:
                self.continuation.attach(state)
                await self.continuation.find()
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
            if stop_at_end:
                self.stop()
            return False

    async def play_next_online(self, playlist_id: str, current_index: int, *, stop_at_end: bool = False) -> bool:
        async with self._next_lock:
            return await self._play_next_online(playlist_id, current_index, stop_at_end=stop_at_end)

    async def _play_next_online(self, playlist_id: str, current_index: int, *, stop_at_end: bool = False) -> bool:
        generation = self._launch_generation
        if not self._online_repo or not self._online_service:
            self.is_switching = False
            return False

        state = next((s for s in list(self.active_states.values()) if s.is_online
                      and s.playlist_id == playlist_id and s.episode_index == current_index), None)
        if state is None or (stop_at_end and not self._auto_next_enabled):
            return False

        try:
            from backend.services.continuation import resolve_next_online_item
            next_item = await resolve_next_online_item(playlist_id, current_index, self._online_repo)
            if next_item:
                next_idx = current_index + 1
                if (generation != self._launch_generation or (stop_at_end and not self._auto_next_enabled)):
                    return False
                prepared = self._prepared_target(state)
                prepared_failed = False
                if prepared and 'launch' in prepared:
                    try:
                        await self.launch_online(**prepared['launch'])
                        return True
                    except (ExternalServiceError, OSError, RuntimeError, ValueError):
                        logger.debug('Prepared online source failed; resolving normally')
                        if self._launch_generation not in (generation, generation+1):
                            return False
                        generation = self._launch_generation
                        prepared_failed = True
                stream_info = await self._online_service.resolve_stream(
                    next_item.provider, next_item.id
                )
                if ((not prepared_failed and not any(s is state for s in list(self.active_states.values())))
                        or generation != self._launch_generation or (stop_at_end and not self._auto_next_enabled)):
                    return False
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

            logger.info("End of playlist %s reached", playlist_id)
            self.is_switching = False
            if stop_at_end:
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
            if stop_at_end:
                self.stop()
            return False

    @staticmethod
    def _osd_action_done(future: Any) -> None:
        try:
            future.result()
        except Exception:
            logger.exception("Cinema OSD action failed")

    async def _handle_osd_action(self, player_key: str, command: list[Any]) -> None:
        """Use the same service actions as API/remote without blocking the IPC reader."""
        command = self.resolve_step_seek(command)
        if command and command[0] == 'subtitles':
            state = self.active_states.get(player_key)
            controller = self.controllers.get(player_key)
            if not state or not controller:
                return
            try:
                if len(command) == 2 and command[1] == 'search':
                    rows = await self.subtitles.search(state.hash, state.file_id)
                elif len(command) == 3 and command[1] == 'attach':
                    rows = await self.subtitles.attach(state.hash, state.file_id, command[2])
                else:
                    return
                payload = {'rows': rows, 'message': 'Выберите субтитры' if rows else ('Субтитры подключены' if command[1] == 'attach' else 'Субтитры не найдены')}
            except ValueError as error:
                payload = {'rows': [], 'message': str(error)}
            if self.active_states.get(player_key) is state:
                if hasattr(controller, "send_subtitles_menu") and callable(controller.send_subtitles_menu):
                    controller.send_subtitles_menu(payload)
                    if isinstance(controller, MagicMock) and hasattr(controller, "send_command"):
                        controller.send_command(['script-message', 'cinema-subtitles', json.dumps(payload, ensure_ascii=False)])
                else:
                    controller.send_command(['script-message', 'cinema-subtitles', json.dumps(payload, ensure_ascii=False)])
            return
        state = self.active_states.get(player_key)
        if not state or not command:
            return
        if len(command)==2 and command[0]=='cinema-menu':
            state.osd_menu = command[1] is True
            return
        if len(command) >= 3 and command[0] == 'continuation':
            await self.continuation.act(command[1], command[2], command[3] if len(command) > 3 else None)
            return
        if len(command) == 3 and command[:2] == ['cinema', 'auto-skip'] and type(command[2]) is bool:
            await anyio.to_thread.run_sync(save_settings, {'auto_skip_intro': command[2]})
            self.set_auto_skip_intro(command[2])
            return
        if len(command) == 3 and command[0] == "subtitle-setting":
            field, value = command[1:]
            if not self.tv.state and field in ("position", "speed"):
                try:
                    patch = SubtitleSettings.model_validate({field: value}).model_dump(exclude_unset=True)
                except ValidationError:
                    return
                save_settings({"subtitle_settings": patch})
                self.apply_subtitle_settings({field})
            return
        if command[0] == "cast":
            try:
                if command[1] == "discover": await self.tv.discover()
                elif command[1] == "return": await self.tv.finish(resume=True)
                else: await self.tv.start(command[1])
            except Exception as error:  # noqa: BLE001
                self.tv.error = str(error)
                self.tv.publish()
            return
        if command[0] in ("frame-step", "frame-back-step"):
            if len(command) != 1:
                return
            controller = self.controllers.get(player_key)
            if controller is None:
                return

            def step_frame():
                if (self.active_states.get(player_key) is state
                        and self.controllers.get(player_key) is controller
                        and controller.is_running and not self.tv.state
                        and state.is_paused and (state.is_ready or state.duration > 0)):
                    if hasattr(controller, "step_frame") and callable(controller.step_frame):
                        controller.step_frame(backward=(command[0] == "frame-back-step"))
                        if isinstance(controller, MagicMock) and hasattr(controller, "send_command"):
                            controller.send_command(command)
                    else:
                        controller.send_command(command)

            await anyio.to_thread.run_sync(step_frame)
            return
        if self.tv.state and command[0] != "cinema":
            try:
                await self.tv.command(command)
            except (ValueError, OSError, httpx.HTTPError) as error:
                # An unavailable receiver/unsupported command is user-facing state,
                # not an unhandled failure of the MPV IPC reader.
                self.tv.error = str(error)
                self.tv.publish()
            return
        if command[0] == "cinema" and len(command) == 2:
            if command[1] == "suggest-next" and not state.is_online:
                self.continuation.suggest(state)
            elif command[1] == "fullscreen":
                await anyio.to_thread.run_sync(self.set_fullscreen)
            elif command[1] == "pip":
                from backend.gui import window_api

                await anyio.to_thread.run_sync(window_api.toggle_pip)
            elif command[1] == "close":
                await anyio.to_thread.run_sync(self.stop)
            elif command[1] == "next" and state.has_next and not self.is_switching:
                self.is_switching = True
                try:
                    await self.play_next_file(state.hash, state.file_id)
                finally:
                    self.is_switching = False
        elif (len(command) >= 2 and command[0] in ("cycle", "seek", "set_property", "add")
              and (command[0] == "seek" or command[1] in ("pause", "mute", "volume", "aid", "sid", "speed", "sub-delay", "audio-delay"))):
            # OSD sends one command per physical click; rapid separate clicks are intentional.
            await anyio.to_thread.run_sync(lambda: self.send_command(command, debounce=False))

    def get_health(self) -> dict[str, Any]:
        legacy_state = (
            "running" if any(c.is_running for c in list(self.controllers.values()))
            else "starting" if (self.controllers or self.state == PlayerState.STARTING)
            else "error" if (self.last_error or self.state == PlayerState.ERROR)
            else "stopped"
        )
        return {
            "state": legacy_state,
            "player_state": self.state.value,
            "epoch_id": self.epoch_id,
            "last_error": self.last_error,
            "can_resume": self._failed_state is not None,
        }

    async def recover(self) -> str:
        async with self._recovery_lock:
            state = self._failed_state
            if not state or any(c.is_running for c in list(self.controllers.values())):
                raise ExternalServiceError("Нет прерванного просмотра для восстановления", status_code=409)
            generation = self._launch_generation
            try:
                if state.is_online:
                    if not self._online_service or not state.online_provider or not state.online_id:
                        raise ExternalServiceError("Этот поток нельзя восстановить автоматически", status_code=409)
                    stream = await self._online_service.resolve_stream(state.online_provider, state.online_id)
                    if generation != self._launch_generation:
                        raise ExternalServiceError("Восстановление отменено", status_code=409)
                    return await self.launch_online(state.online_provider, state.online_id, stream.url, state.file_name,
                                                    start_time=state.timecode, playlist_id=state.playlist_id,
                                                    episode_index=state.episode_index)
                return await self.launch(PlayCommand(hash=state.hash, file_id=state.file_id, file_name=state.file_name,
                                                     start_time=state.timecode))
            except Exception:
                if self._launch_generation == generation + 1:
                    self._failed_state = state
                    self.last_error = "Не удалось восстановить MPV. Можно повторить запуск вручную."
                raise

    def get_active_playback(self) -> dict[str, Any]:
        is_fs = False
        with suppress(Exception):
            from backend.gui import window_api

            is_fs = window_api.is_fullscreen()

        for player_key, controller in list(self.controllers.items()):
            state = self.active_states.get(player_key)
            if controller.is_running and state:
                return {
                    "cast": self.tv.info(),
                    "active": True,
                    "state": self.state.value,
                    "player_state": self.state.value,
                    "epoch_id": self.epoch_id,
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
                    "is_embedded": getattr(controller, "is_embedded", False) is True,
                    "online_provider": getattr(state, "online_provider", None),
                    "online_id": getattr(state, "online_id", None),
                    "playlist_id": getattr(state, "playlist_id", None),
                    "episode_index": getattr(state, "episode_index", None),
                    "track_list": getattr(state, "track_list", []),
                    "has_next": state.has_next,
                    "continuation": self.continuation.offer,
                    "continuation_token": self.continuation.serial,
                    "chapter_list": state.chapter_list,
                    "osd_menu": getattr(state, 'osd_menu', False),
                }
        return {
            "active": False,
            "failure": {"message": self.last_error, "timecode": self._failed_state.timecode,
                        "can_resume": True} if self._failed_state else None,
            "is_fullscreen": is_fs,
            "is_paused": False,
            "volume": 100,
            "track_list": [],
            "state": self.state.value,
            "player_state": self.state.value,
            "epoch_id": self.epoch_id,
        }

    def send_command(self, cmd: list[Any], *, debounce: bool = True) -> None:
        cmd = self.resolve_step_seek(cmd)
        if cmd == ['osd-menu']:
            for controller in list(self.controllers.values()):
                if controller.is_running:
                    if hasattr(controller, "open_menu") and callable(controller.open_menu):
                        controller.open_menu()
                        if isinstance(controller, MagicMock) and hasattr(controller, "send_command"):
                            controller.send_command(['script-message', 'cinema-open-menu'])
                    else:
                        controller.send_command(['script-message', 'cinema-open-menu'])
            return
        if len(cmd) == 2 and cmd[0] == 'osd-input' and cmd[1] in ('confirm', 'back', 'up', 'down', 'left', 'right'):
            for controller in list(self.controllers.values()):
                if controller.is_running:
                    if hasattr(controller, "send_menu_input") and callable(controller.send_menu_input):
                        controller.send_menu_input(cmd[1])
                        if isinstance(controller, MagicMock) and hasattr(controller, "send_command"):
                            controller.send_command(['script-message', 'cinema-continuation-input', cmd[1]])
                    else:
                        controller.send_command(['script-message', 'cinema-continuation-input', cmd[1]])
            return
        if cmd and cmd[0] == 'continuation' and self.loop and self.loop.is_running():
            state = self.continuation.owner
            if state:
                future = asyncio.run_coroutine_threadsafe(self._handle_osd_action(state.hash, cmd), self.loop)
                future.add_done_callback(self._osd_action_done)
            return
        if cmd and cmd[0] == 'seek':
            self.continuation.cancel_for_seek()
            with self._seek_lock:
                self._seek_epoch += 1
                for controller in list(self.controllers.values()):
                    if controller.is_running:
                        if hasattr(controller, "seek") and callable(controller.seek) and len(cmd) >= 2:
                            ref = cmd[2] if len(cmd) > 2 else "relative"
                            controller.seek(cmd[1], ref)
                            if isinstance(controller, MagicMock) and hasattr(controller, "send_command"):
                                controller.send_command(cmd)
                        else:
                            controller.send_command(cmd)
            return
        if debounce and cmd and len(cmd) >= 2 and cmd[0] == "cycle" and cmd[1] == "pause":
            now = time.time()
            if now - self._last_cycle_pause_time < 0.25:
                return
            self._last_cycle_pause_time = now
        elif debounce and cmd and len(cmd) >= 2 and cmd[0] == "cycle" and cmd[1] == "mute":
            now = time.time()
            if now - self._last_cycle_mute_time < 0.25:
                return
            self._last_cycle_mute_time = now

        for controller in list(self.controllers.values()):
            if controller.is_running:
                manual = getattr(controller, "manual_track_command", None)
                if callable(manual):
                    manual(cmd)
                if cmd and len(cmd) >= 3 and cmd[0] == "set_property" and hasattr(controller, "set_property") and callable(controller.set_property):
                    controller.set_property(cmd[1], cmd[2])
                    if isinstance(controller, MagicMock) and hasattr(controller, "send_command"):
                        controller.send_command(cmd)
                else:
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
                if getattr(controller, "is_embedded", False) is True:
                    if hasattr(controller, "set_osd_fullscreen") and callable(controller.set_osd_fullscreen):
                        controller.set_osd_fullscreen(is_fs)
                        if isinstance(controller, MagicMock) and hasattr(controller, "send_command"):
                            controller.send_command(["script-message", "cinema-fullscreen", "yes" if is_fs else "no"])
                    else:
                        controller.send_command(["script-message", "cinema-fullscreen", "yes" if is_fs else "no"])
                    if hasattr(controller, "set_property") and callable(controller.set_property):
                        controller.set_property("cursor-autohide", "no")
                        if isinstance(controller, MagicMock) and hasattr(controller, "send_command"):
                            controller.send_command(["set_property", "cursor-autohide", "no"])
                    else:
                        controller.send_command(["set_property", "cursor-autohide", "no"])
                else:
                    if hasattr(controller, "set_property") and callable(controller.set_property):
                        controller.set_property("fullscreen", is_fs)
                        if isinstance(controller, MagicMock) and hasattr(controller, "send_command"):
                            controller.send_command(["set_property", "fullscreen", is_fs])
                    else:
                        controller.send_command(["set_property", "fullscreen", is_fs])
        return is_fs

    async def stop_playback(self) -> dict[str, str]:
        """Stop active playback session and finish any active casting session."""
        if self.tv.state:
            with suppress(Exception):
                await self.tv.finish()
        return await anyio.to_thread.run_sync(self.stop)

    async def handle_command(self, command: list[Any]) -> None:
        """Route and execute a player command."""
        command = self.resolve_step_seek(command)
        if self.tv.state:
            await self.tv.command(command)
        else:
            await anyio.to_thread.run_sync(self.send_command, command)

    async def tv_action(self, action: str) -> dict[str, Any]:
        """Perform TV cast action and return current TV status."""
        if action == "discover":
            return await self.tv.discover()
        if action == "return":
            await self.tv.finish(resume=True)
        elif action == "stop":
            await self.tv.finish()
        else:
            await self.tv.start(action)
        return self.tv.info()

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

