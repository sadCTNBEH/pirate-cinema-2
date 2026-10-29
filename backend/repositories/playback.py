from typing import Any

from backend.models.playback import PlaybackState
from backend.repositories.base import BaseRepository
from backend.repositories.db import Database


class PlaybackRepository(BaseRepository):
    def __init__(self, db: Database):
        super().__init__(db)

    def file_choice(self, hash: str, intent: str, file_id: int | None = None) -> int | None:
        with self.connection() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS torrent_file_choices '
                         '(hash TEXT, intent TEXT, file_id INTEGER, PRIMARY KEY(hash, intent))')
            if file_id is not None:
                conn.execute('INSERT OR REPLACE INTO torrent_file_choices VALUES (?, ?, ?)',
                             (hash, intent, file_id))
                return file_id
            row = conn.execute('SELECT file_id FROM torrent_file_choices WHERE hash=? AND intent=?',
                               (hash, intent)).fetchone()
            return row[0] if row else None

    def file_intent(self, hash: str, file_id: int) -> dict | None:
        import json
        # Initializes the small preference table for existing installations too.
        self.file_choice(hash, '')
        with self.connection() as conn:
            row = conn.execute('SELECT intent FROM torrent_file_choices WHERE hash=? AND file_id=? '
                               'ORDER BY rowid DESC LIMIT 1', (hash, file_id)).fetchone()
        if not row:
            return None
        season, episode, absolute = json.loads(row[0])
        return dict(season=season, episode=episode, absolute=absolute)

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
