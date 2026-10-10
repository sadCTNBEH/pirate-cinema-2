import logging
from typing import Any, Optional

from backend.models.playback import PlaybackState
from backend.repositories.base import BaseRepository
from backend.repositories.db import Database
from backend.repositories.library import LibraryRepository

logger = logging.getLogger(__name__)


class PlaybackRepository(BaseRepository):
    def __init__(self, db: Optional[Database] = None):
        super().__init__(db)

    def get_previous_progress(self, hash: str, file_id: int) -> Optional[Any]:
        with self.connection() as conn:
            try:
                return conn.execute(
                    """SELECT playback_timecode, is_watched, audio_track, subtitle_track 
                       FROM media_file_history 
                       WHERE torrent_hash=? AND file_index=?""",
                    (hash, file_id),
                ).fetchone()
            except Exception:
                logger.exception("Could not get previous progress")
                return None

    def save_progress(self, state: PlaybackState) -> None:
        with self.connection() as conn:
            try:
                conn.execute(
                    """UPDATE media_file_history
                       SET playback_timecode = ?, audio_track = ?, subtitle_track = ?, is_watched = ?
                       WHERE torrent_hash = ? AND file_index = ?
                    """,
                    (
                        state.timecode,
                        state.audio_track,
                        state.subtitle_track,
                        int(state.is_watched),
                        state.hash,
                        state.file_id,
                    ),
                )
            except Exception:
                logger.exception("Could not save progress")

    def get_state(self, hash: str, file_id: int) -> Optional[Any]:
        with self.connection() as conn:
            try:
                return conn.execute(
                    """SELECT playback_timecode, is_watched, audio_track, subtitle_track, playback_duration
                       FROM media_file_history 
                       WHERE torrent_hash=? AND file_index=?""",
                    (hash, file_id),
                ).fetchone()
            except Exception:
                logger.exception("Could not get previous progress")
                return None

    # Использование единой реализации из LibraryRepository (устранено дублирование)
    parse_ep = staticmethod(LibraryRepository.parse_ep)


# Псевдоним для обратной совместимости до рефакторинга сервисов
MpvRepository = PlaybackRepository