from typing import Any

from backend.models.playback import PlaybackState
from backend.repositories.base import BaseRepository
from backend.repositories.db import Database


class PlaybackRepository(BaseRepository):
    def get_sync(self, hash: str, file_id: int) -> tuple[float, float]:
        with self.connection() as conn:
            row = conn.execute('SELECT sub_delay,audio_delay FROM playback_sync WHERE hash=? AND file_id=?',
                               (hash, file_id)).fetchone()
            return tuple(row) if row else (0.0, 0.0)

    def save_sync(self, hash: str, file_id: int, prop: str, value: float) -> None:
        import math
        if prop not in ('sub-delay', 'audio-delay') or not math.isfinite(value):
            return
        column = prop.replace('-', '_')
        with self.connection() as conn:
            conn.execute(f'''INSERT INTO playback_sync(hash,file_id,{column}) VALUES(?,?,?)
                ON CONFLICT(hash,file_id) DO UPDATE SET {column}=excluded.{column}''', (hash, file_id, value))

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
        return {"season": season, "episode": episode, "absolute": absolute}

    def logical_progress(self, hash: str, season: int | None = None,
                         episode: int | None = None, *, latest: bool = False) -> dict | None:
        """Resolve by catalog identity only. Never merge by a release title."""
        with self.connection() as conn:
            row = conn.execute("SELECT imdb_id FROM media_metadata WHERE torrent_hash=?", (hash,)).fetchone()
            if not row or not row['imdb_id']:
                return None
            clause = '' if latest else 'AND h.season IS ? AND h.episode IS ?'
            params = (row['imdb_id'],) if latest else (row['imdb_id'], season, episode)
            result = conn.execute(f"""SELECT h.* FROM media_file_history h
                LEFT JOIN media_metadata m ON m.torrent_hash=h.torrent_hash
                WHERE COALESCE(h.imdb_id,m.imdb_id)=? AND h.torrent_hash NOT LIKE 'online:%'
                AND h.playback_duration>0 {clause}
                ORDER BY h.last_played_at DESC, h.rowid DESC LIMIT 1""", params).fetchone()
            return dict(result) if result else None

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
            # A newer playback session owns shared resume progress, even if an
            # older PC/phone session sends a delayed final event afterwards.
            conn.execute('CREATE TABLE IF NOT EXISTS playback_progress_owner '
                         '(hash TEXT, file_id INTEGER, generation INTEGER, PRIMARY KEY(hash,file_id))')
            conn.execute('INSERT INTO playback_progress_owner VALUES (?,?,?) '
                         'ON CONFLICT(hash,file_id) DO UPDATE SET generation=excluded.generation '
                         'WHERE excluded.generation >= generation',
                         (state.hash, state.file_id, state.progress_generation))
            owner = conn.execute('SELECT generation FROM playback_progress_owner WHERE hash=? AND file_id=?',
                                 (state.hash, state.file_id)).fetchone()
            if owner[0] != state.progress_generation:
                return
            conn.execute(
                """UPDATE media_file_history
                   SET last_played_at = strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                       playback_timecode = ?,
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
