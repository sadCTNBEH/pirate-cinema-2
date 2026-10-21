from typing import Any

from backend.models.playback import PlaybackState
from backend.repositories.base import BaseRepository
from backend.repositories.db import Database


class PlaybackRepository(BaseRepository):
    def __init__(self, db: Database):
        super().__init__(db)

    def get_previous_progress(self, hash: str, file_id: int) -> Any | None:
        with self.connection() as conn:
            return conn.execute(
                """SELECT playback_timecode, playback_duration, is_watched, audio_track, subtitle_track
                   FROM media_file_history
                   WHERE torrent_hash=? AND file_index=?""",
                (hash, file_id),
            ).fetchone()

    def save_progress(self, state: PlaybackState) -> None:
        tc = max(0, int(state.timecode))
        dur = max(0, int(state.duration))
        if dur > 0 and tc > dur:
            tc = dur
        with self.connection() as conn:
            conn.execute(
                """UPDATE media_file_history
                   SET playback_timecode = ?,
                       playback_duration = ?,
                       audio_track = ?,
                       subtitle_track = ?,
                       is_watched = CASE WHEN is_watched = 1 THEN 1 ELSE ? END
                   WHERE torrent_hash = ? AND file_index = ?
                """,
                (
                    tc,
                    dur,
                    state.audio_track,
                    state.subtitle_track,
                    int(state.is_watched),
                    state.hash,
                    state.file_id,
                ),
            )

    def get_state(self, hash: str, file_id: int) -> Any | None:
        with self.connection() as conn:
            return conn.execute(
                """SELECT playback_timecode, is_watched, audio_track, subtitle_track, playback_duration
                   FROM media_file_history
                   WHERE torrent_hash=? AND file_index=?""",
                (hash, file_id),
            ).fetchone()
