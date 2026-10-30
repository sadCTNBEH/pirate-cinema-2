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
from pathlib import Path
from typing import Any

import anyio
import httpx

from backend.core.settings import (
    get_data_dir,
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
from backend.services.introdb import IntroDB
from backend.services.torrent_selection import episode_info, next_file, select_files

logger = logging.getLogger(__name__)
NEXT_PREPARE_SECONDS = 90
NEXT_PREPARE_TIMEOUT = 5
NEXT_PREPARED_TTL = 120


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
        mpv_controller_factory: Callable[[], MPVController],
        torrserver_client: Any,
        settings_provider: Callable[[], str],
        library_repo: LibraryRepository | None = None,
        metadata_service: Any = None,
        online_repo: Any = None,
        online_service: Any = None,
        search_service: Any = None,
        magnet_service: Any = None,
    ):
        self._repo = playback_repo
        from backend.services.subtitles import SubtitleService
        self.subtitles = SubtitleService(self)
        self._history = history_repo
        self._metadata = metadata_repo
        self._controller_factory = mpv_controller_factory
        self._torrserver = torrserver_client
        self._get_ts_url = settings_provider
        self._library_repo = library_repo
        self._metadata_service = metadata_service
        self._online_repo = online_repo
        self._online_service = online_service

        from backend.services.tv_session import TVSession
        self.tv = TVSession(self)

        self.controllers: dict[str, MPVController] = {}
        self.active_states: dict[str, PlaybackState] = {}

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
        from backend.services.continuation import Continuation
        self.continuation = Continuation(self, search_service, magnet_service)

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

    def set_auto_skip_intro(self, enabled):
        for controller in list(self.controllers.values()):
            controller.set_auto_skip(bool(enabled))

    def set_seek_step(self, seconds: int) -> None:
        for controller in list(self.controllers.values()):
            setter = getattr(controller, "set_seek_step", None)
            if callable(setter):
                setter(seconds)

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
            files = await self._torrserver.torrent_video_files(self._get_ts_url(), hash)
        except (httpx.HTTPError, TimeoutError) as error:
            raise ExternalServiceError('Не удалось получить файлы TorrServer. Выберите другую раздачу.', status_code=502) from error
        result = select_files(files, **intent)
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
        intent = self._file_intents.get((hash, file_id))
        if intent and intent.get('season') is None and intent.get('episode') is None and intent.get('absolute') is None:
            intent = None
        match = next_file(files, file_id, intent)
        if match:
            return match
        current = next((f for f in files if str(f.get('id')) == str(file_id)), None)
        if not current:
            return None
        info = episode_info(current.get('path') or current.get('name', ''))
        intent = intent or info
        if intent.get('episode') is None:
            return None
        key = json.dumps([intent.get('season'), intent['episode'] + 1,
                          intent['absolute'] + 1 if intent.get('absolute') is not None else None])
        confirmed = await anyio.to_thread.run_sync(self._repo.file_choice, hash, key)
        matched = next_file(files, file_id, intent, confirmed) if isinstance(confirmed, int) else None
        if matched or not self._metadata_service:
            return matched
        from backend.services.continuation import catalog_next
        media_id = await anyio.to_thread.run_sync(self._metadata.get_imdb_id, hash)
        if not isinstance(media_id, str) or intent.get('season') is None:
            return None
        meta = await self._metadata_service.movie_meta(media_id, 'series')
        target, _ = catalog_next(meta, (intent['season'], intent['episode']))
        if target:
            matched = select_files(files, **target)['file']
            if matched:
                self._file_intents[(hash, matched['id'])] = target
        return matched

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
        if (not self._auto_next_enabled or not state.has_next or self.is_switching
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
                target = dict(candidate[1])
                if state.is_online:
                    info = await self._online_service.resolve_stream(target['provider'], target['id'])
                    target['launch'] = {'provider': target['provider'], 'video_id': target['id'],
                                        'stream_url': info.url, 'title': info.title, 'thumbnail': info.thumbnail,
                                        'duration': info.duration, 'start_time': 0, 'playlist_id': state.playlist_id,
                                        'episode_index': state.episode_index+1}
                else:
                    # This client has no bounded, low-priority preload operation.
                    # Prepare metadata/URL without opening another video stream.
                    target['url'] = self._torrserver.stream_url(self._get_ts_url(), state.hash,
                                                               target['file']['id'], target['file']['name'])
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
                    controller.send_command(['seek', max(0, min(state.duration, position)), 'absolute+exact'])
        await anyio.to_thread.run_sync(commit)

    def _schedule_save(self, state: PlaybackState) -> None:
        if not self.loop or not self.loop.is_running():
            return
        snapshot = replace(state, track_list=list(state.track_list))
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

    def _begin_launch(self) -> int:
        self.continuation.reset()
        for task in self._segment_tasks:
            task.cancel()
        self._cancel_preparation()
        self._next_candidates.clear()
        self._preparation_attempt = None
        self._advance_attempt = None
        self._seek_epoch += 1
        self._launch_generation += 1
        self._failed_state = None
        self.last_error = None
        for controller in list(self.controllers.values()):
            if not controller.is_running and hasattr(controller, 'cancel_start'):
                controller.cancel_start()
        return self._launch_generation

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
            await self._torrserver.require_ram_cache(self._get_ts_url())
        existing = self.active_states.get(command.hash)
        if (existing and existing.file_id == command.file_id and command.start_time in (None, 0)
                and any(c.is_running for c in self.controllers.values())):
            return 'launched'
        if self.tv.state:
            await self.tv.finish()
        generation = self._begin_launch()
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
                if hasattr(self._torrserver, "torrent_video_files"):
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
        url = prepared_url or self._torrserver.stream_url(
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
            resume_candidate=logical_resume if not row or not dict(row).get("playback_duration") else None,
        )

        if running_controller:
            running_controller._awaiting_media = True
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
                resume_candidate=logical_resume if not row or not dict(row).get("playback_duration") else None,
            )

            running_controller.on_progress = lambda name, val, k=player_key, g=generation: (
                self._handle_progress(k, name, val) if g == self._launch_generation else None
            )
            running_controller.on_end = lambda reason, k=player_key, g=generation: self._handle_end(k, reason) if g == self._launch_generation else None

            await anyio.to_thread.run_sync(lambda: self._launch_controller(
                running_controller, generation, {'url': url, 'title': command.file_name, 'start_time': start_time,
                                                 'audio_track': audio_track, 'subtitle_track': subtitle_track}, load_only=True))

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
                resume_candidate=logical_resume if not row or not dict(row).get("playback_duration") else None,
            )

            controller = self._controller_factory()
            self.controllers[player_key] = controller

            controller.on_progress = lambda name, val, k=player_key, g=generation: (
                self._handle_progress(k, name, val) if g == self._launch_generation else None
            )
            controller.on_end = lambda reason, k=player_key, g=generation: self._handle_end(k, reason) if g == self._launch_generation else None

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
                await anyio.to_thread.run_sync(self._launch_controller, controller, generation, launch_kwargs)
            except (OSError, RuntimeError) as e:
                logger.exception("Failed to launch player process")
                if self.controllers.get(player_key) is controller:
                    self.controllers.pop(player_key, None)
                    self.active_states.pop(player_key, None)
                with suppress(OSError, RuntimeError):
                    controller.stop()
                raise ExternalServiceError(
                    _player_error_message(e, prefs.get("language")), status_code=500
                ) from e

        await self._refresh_next_available(player_key, next_files)
        self._start_segments(player_key, season, episode, movie=not is_series)
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
        stream_headers = {}
        if provider == 'animego' and self._online_service:
            stream_headers = self._online_service.get_provider(provider).stream_headers(video_id)
        if self.tv.state:
            await self.tv.finish()
        generation = self._begin_launch()
        self._explicit_tracks = (None, None)
        self.loop = asyncio.get_running_loop()
        self.is_switching = False

        prefs = load_settings()
        self.set_auto_next(prefs.get('auto_next', True))
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

        await self._check_launch_intent(generation)
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
            running_controller._awaiting_media = True
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

            running_controller.on_progress = lambda name, val, k=player_key, g=generation: (
                self._handle_progress(k, name, val) if g == self._launch_generation else None
            )
            running_controller.on_end = lambda reason, k=player_key, g=generation: self._handle_end(k, reason) if g == self._launch_generation else None

            await anyio.to_thread.run_sync(
                lambda: self._launch_controller(running_controller, generation,
                                               {'url': stream_url, 'title': title, 'start_time': start_time, '_source': provider, '_headers': stream_headers}, load_only=True)
            )
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

            controller.on_progress = lambda name, val, k=player_key, g=generation: (
                self._handle_progress(k, name, val) if g == self._launch_generation else None
            )
            controller.on_end = lambda reason, k=player_key, g=generation: self._handle_end(k, reason) if g == self._launch_generation else None

            wid: int | None = None
            if prefs.get("embedded_player", True):
                with suppress(Exception):
                    from backend.gui import window_api

                    wid = window_api.ensure_player_hwnd()

            launch_kwargs: dict[str, Any] = {
                "mpv_path": mpv_bin,
                "url": stream_url,
                "_source": provider,
                "_headers": stream_headers,
                "title": title,
                "start_time": start_time,
            }
            if wid is not None:
                launch_kwargs["wid"] = wid

            try:
                await anyio.to_thread.run_sync(self._launch_controller, controller, generation, launch_kwargs)
            except (OSError, RuntimeError) as e:
                logger.exception("Failed to launch player process for online stream")
                if self.controllers.get(player_key) is controller:
                    self.controllers.pop(player_key, None)
                    self.active_states.pop(player_key, None)
                with suppress(OSError, RuntimeError):
                    controller.stop()
                raise ExternalServiceError(
                    _player_error_message(e, prefs.get("language")), status_code=500
                ) from e

        await self._refresh_next_available(player_key)
        # Online providers without an established IMDb/episode mapping use MPV chapters only.
        controller = self.controllers.get(player_key)
        if controller:
            controller.set_segments([], bool(prefs.get('auto_skip_intro', False)))
        return "launched"

    async def _refresh_next_available(self, player_key: str, files: list[dict[str, Any]] | None = None) -> None:
        state = self.active_states.get(player_key)
        controller = self.controllers.get(player_key)
        if not state or not controller:
            return
        controller.send_command(["script-message", "cinema-next", "no"])
        has_next = False
        next_target = None
        try:
            if state.is_online:
                if self._online_repo and state.playlist_id and state.episode_index is not None:
                    playlist = await anyio.to_thread.run_sync(self._online_repo.get_playlist, state.playlist_id)
                    has_next = bool(playlist and 0 <= state.episode_index < len(playlist.items) - 1)
                    if has_next:
                        item = playlist.items[state.episode_index+1]
                        next_target = {'provider': item.provider, 'id': item.id}
            else:
                if files is None:
                    files = await self._torrserver.torrent_video_files(self._get_ts_url(), state.hash)
                if isinstance(files, list):
                    item = await self._next_torrent_file(files, state.hash, state.file_id)
                    has_next = item is not None
                    if item:
                        next_target = {'file': item}
        except (httpx.HTTPError, ExternalServiceError, sqlite3.Error, OSError, RuntimeError, ValueError, TypeError, TimeoutError):
            logger.debug("Could not determine next episode availability", exc_info=True)
        if self.active_states.get(player_key) is state and self.controllers.get(player_key) is controller:
            state.has_next = has_next
            if next_target:
                self._next_candidates[player_key] = (state, next_target)
            controller.send_command(["script-message", "cinema-next", "yes" if has_next else "no"])

    def stop(self) -> dict[str, str]:
        if self.tv.state and self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.tv.finish(), self.loop)
        self.continuation.reset()
        self._cancel_preparation()
        self._next_candidates.clear()
        self._preparation_attempt = None
        self._seek_epoch += 1
        self._launch_generation += 1
        self._failed_state = None
        self.last_error = None
        for controller in list(self.controllers.values()):
            if hasattr(controller, 'cancel_start'):
                controller.cancel_start()
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

            with suppress(Exception):
                from backend.gui import window_api

                window_api.hide_player_panel()
            return {"status": "stopped"}

    async def stop_all(self) -> None:
        """Stop live and starting players off the application event loop."""
        await self.tv.finish()
        for device in self.tv.devices.values():
            await device.close()
        preparation = self._preparation
        await anyio.to_thread.run_sync(self.stop)
        if preparation:
            with suppress(asyncio.CancelledError):
                await asyncio.wrap_future(preparation)
        pending = list(self._pending_saves)
        if pending:
            try:
                await asyncio.wait_for(asyncio.gather(*(asyncio.wrap_future(future) for future in pending),
                                                       return_exceptions=True), timeout=3)
            except TimeoutError:
                logger.warning('Timed out flushing playback progress during shutdown')

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
                        self.controllers[player_key].send_command(['seek', target, 'absolute+exact'])
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

        if is_eof and not state.is_online:
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
            else:
                files = await self._torrserver.torrent_video_files(torrserver_url, hash)
                files = self.sort_video_files(files)

            next_f = prepared['file'] if prepared and 'file' in prepared else await self._next_torrent_file(
                files, hash, file_id)
            if next_f:
                intent = self._file_intents.get((hash, file_id))
                if intent and intent.get('episode') is not None:
                    following = self._file_intents.get((hash, next_f['id'])) or {**intent, 'episode': intent['episode'] + 1}
                    if intent.get('absolute') is not None and following.get('absolute') == intent.get('absolute'):
                        following['absolute'] += 1
                    self._file_intents[(hash, next_f['id'])] = following
                    key = json.dumps([following.get('season'), following['episode'], following.get('absolute')])
                    await anyio.to_thread.run_sync(self._repo.file_choice, hash, key, next_f['id'])
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
            pl = await anyio.to_thread.run_sync(
                self._online_repo.get_playlist, playlist_id
            )
            if not pl or not pl.items:
                self.is_switching = False
                return False

            next_idx = current_index + 1
            if next_idx < len(pl.items):
                if (generation != self._launch_generation or (stop_at_end and not self._auto_next_enabled)):
                    return False
                next_item = pl.items[next_idx]
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
            from backend.core.settings import save_settings
            await anyio.to_thread.run_sync(save_settings, {'auto_skip_intro': command[2]})
            self.set_auto_skip_intro(command[2])
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
        return {"state": "running" if any(c.is_running for c in list(self.controllers.values())) else "starting" if self.controllers else "error" if self.last_error else "stopped",
                "last_error": self.last_error, "can_resume": self._failed_state is not None}

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
        }

    def send_command(self, cmd: list[Any], *, debounce: bool = True) -> None:
        cmd = self.resolve_step_seek(cmd)
        if cmd == ['osd-menu']:
            for controller in list(self.controllers.values()):
                if controller.is_running:
                    controller.send_command(['script-message','cinema-open-menu'])
            return
        if len(cmd)==2 and cmd[0]=='osd-input' and cmd[1] in ('confirm','back','up','down','left','right'):
            for controller in list(self.controllers.values()):
                if controller.is_running:
                    controller.send_command(['script-message','cinema-continuation-input',cmd[1]])
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
                    controller.send_command(["script-message", "cinema-fullscreen", "yes" if is_fs else "no"])
                    controller.send_command(["set_property", "cursor-autohide", "no"])
                else:
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

