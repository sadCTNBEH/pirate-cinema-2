from datetime import datetime, timezone
from backend.repositories.db import get_connection

def mark_played(torrent_hash: str, file_index: int, file_name: str, file_path: str | None = None):
    now = datetime.now(timezone.utc).isoformat() + "Z"
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO media_file_history (torrent_hash, file_index, file_name, file_path, first_played_at, last_played_at, launch_count)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(torrent_hash, file_index) DO UPDATE SET
                last_played_at = excluded.last_played_at,
                launch_count = launch_count + 1
        """, (torrent_hash, file_index, file_name, file_path, now, now))

def update_progress(torrent_hash: str, file_index: int, timecode: int, duration: int, audio_track: int = 0):
    is_watched = 1 if duration > 0 and (duration - timecode) < 180 else 0
    with get_connection() as conn:
        conn.execute("""
            UPDATE media_file_history
            SET playback_timecode = ?, playback_duration = ?, is_watched = CASE WHEN is_watched = 1 THEN 1 ELSE ? END, audio_track = CASE WHEN ? > 0 THEN ? ELSE audio_track END
            WHERE torrent_hash = ? AND file_index = ?
        """, (timecode, duration, is_watched, audio_track, audio_track, torrent_hash, file_index))
