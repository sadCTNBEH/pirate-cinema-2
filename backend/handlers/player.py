"""Playback session handler (SRP) – encapsulates MPV playback session state."""

import asyncio
import logging
import sqlite3
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any

from backend.repositories import audio, history

logger = logging.getLogger(__name__)


class PlaybackSessionHandler:
    """Обработчик событий воспроизведения (SRP). Инкапсулирует состояние сессии."""

    def __init__(
        self,
        torrent_hash: str,
        file_id: int,
        loop: asyncio.AbstractEventLoop,
        play_next_fn: Callable[[str, int], Awaitable[None]],
    ) -> None:
        self.torrent_hash = torrent_hash
        self.file_id = file_id
        self.loop = loop
        self.play_next_fn = play_next_fn

        # Состояние текущего сеанса
        self.last_timecode: int = 0
        self.last_duration: int = 0
        self.last_aid: int = 0
        self.last_save_time: float = 0.0

        self._lock = threading.Lock()

    def on_progress(self, prop: str, value: Any) -> None:
        if value is None:
            return

        with self._lock:
            if prop == "time-pos":
                try:
                    self.last_timecode = int(value)
                except (ValueError, TypeError):
                    return
            elif prop == "duration":
                try:
                    self.last_duration = int(value)
                except (ValueError, TypeError):
                    return
            elif prop == "aid":
                try:
                    new_aid = int(value)
                    if new_aid > 0 and new_aid != self.last_aid:
                        self.last_aid = new_aid
                        self._save_audio_track(new_aid)
                except (ValueError, TypeError):
                    pass

            now = time.time()
            should_save = (
                self.last_timecode > 0
                and self.last_duration > 0
                and (now - self.last_save_time >= 3.0 or prop == "flush")
            )

            if should_save:
                self._save_progress(now)

    def _save_audio_track(self, aid: int) -> None:
        try:
            audio.set_audio_track(self.torrent_hash, aid, self.file_id)
        except sqlite3.Error as e:
            logger.warning("Failed to save audio track to DB: %s", e)

    def _save_progress(self, current_time: float) -> None:
        try:
            history.update_progress(
                self.torrent_hash,
                self.file_id,
                self.last_timecode,
                self.last_duration,
                self.last_aid,
            )
            self.last_save_time = current_time
        except sqlite3.Error as e:
            logger.warning("Failed to save progress to DB: %s", e)

    def on_end(self, reason: str | None) -> None:
        if reason == "eof":
            logger.info(
                "[Session] Playback reached EOF for %s (file %s). Triggering play_next.",
                self.torrent_hash,
                self.file_id,
            )
            future = asyncio.run_coroutine_threadsafe(
                self.play_next_fn(self.torrent_hash, self.file_id),
                self.loop,
            )

            def _on_done(f: asyncio.Future) -> None:
                try:
                    f.result()
                except asyncio.CancelledError:
                    logger.debug("Play next task was cancelled")
                except Exception:
                    logger.exception("Failed to play next episode via callback")

            future.add_done_callback(_on_done)
