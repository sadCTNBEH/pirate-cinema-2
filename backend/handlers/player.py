import asyncio
import logging
import sqlite3
import time
from urllib import error

from backend.repositories import audio, history

logger = logging.getLogger(__name__)


class PlaybackSessionHandler:
    """Обработчик событий воспроизведения (SRP). Инкапсулирует состояние сессии."""

    def __init__(
        self,
        torrent_hash: str,
        file_id: int,
        loop: asyncio.AbstractEventLoop,
        play_next_fn,
    ):
        self.torrent_hash = torrent_hash
        self.file_id = file_id
        self.loop = loop
        self.play_next_fn = play_next_fn

        # Состояние текущего сеанса
        self.last_timecode = 0
        self.last_duration = 0
        self.last_aid = 0
        self.last_save_time = 0

    def on_progress(self, prop: str, value):
        if value is None:
            return

        if prop == "time-pos":
            self.last_timecode = int(value)
        elif prop == "duration":
            self.last_duration = int(value)
        elif prop == "aid":
            try:
                new_aid = int(value)
                if new_aid > 0 and new_aid != self.last_aid:
                    self.last_aid = new_aid
                    try:
                        audio.set_audio_track(
                            self.torrent_hash, new_aid, self.file_id
                        )
                    except sqlite3.Error as e:
                        logger.warning("Failed to save audio track to DB: %s", e)
            except (ValueError, TypeError):
                pass

        now = time.time()
        should_save = (
            self.last_timecode
            and self.last_duration
            and (now - self.last_save_time >= 3 or prop == "flush")
        )

        if should_save:
            try:
                history.update_progress(
                    self.torrent_hash,
                    self.file_id,
                    self.last_timecode,
                    self.last_duration,
                    self.last_aid,
                )
                self.last_save_time = now
            except sqlite3.Error as e:
                logger.warning("Failed to save progress to DB: %s", e)

    def on_end(self, reason: str):
        if reason == "eof":
            future = asyncio.run_coroutine_threadsafe(
                self.play_next_fn(self.torrent_hash, self.file_id), self.loop
            )

            def _on_done(f):
                try:
                    f.result()
                except (error.URLError, error.HTTPError, OSError):
                    logger.exception("Failed to play next episode via webhook")

            future.add_done_callback(_on_done)
