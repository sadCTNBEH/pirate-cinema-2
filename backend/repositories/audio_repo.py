from backend.repositories.db import get_connection


def get_audio_track(torrent_hash: str, file_index: int | None = None) -> int:
    """Return saved audio track id: per-file first, then torrent-wide fallback."""
    with get_connection() as conn:
        if file_index is not None:
            r = conn.execute(
                "SELECT audio_track FROM media_file_history WHERE torrent_hash=? AND file_index=?",
                (torrent_hash, file_index)
            ).fetchone()
            if r and r["audio_track"] and r["audio_track"] > 0:
                return r["audio_track"]
        r = conn.execute(
            "SELECT track_id FROM media_audio_tracks WHERE torrent_hash=?",
            (torrent_hash,)
        ).fetchone()
        return r["track_id"] if r else 0

def set_audio_track(torrent_hash: str, track_id: int, file_index: int | None = None):
    """Persist audio track preference at file level and torrent-wide level."""
    with get_connection() as conn:
        if file_index is not None:
            conn.execute(
                "UPDATE media_file_history SET audio_track=? WHERE torrent_hash=? AND file_index=?",
                (track_id, torrent_hash, file_index)
            )
        conn.execute(
            "INSERT INTO media_audio_tracks (torrent_hash, track_id) VALUES (?,?) "
            "ON CONFLICT(torrent_hash) DO UPDATE SET track_id=excluded.track_id",
            (torrent_hash, track_id)
        )
