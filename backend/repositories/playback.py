import logging
import re

from backend.models.playback import PlaybackState
from backend.repositories.db import get_connection


logger = logging.getLogger(__name__)

class MpvRepository:
    def __init__(self):
        pass

    def get_previous_progress(self, hash, file_id):
        with get_connection() as conn:
            try:
                return conn.execute(
                    """SELECT playback_timecode, is_watched, audio_track, subtitle_track 
                       FROM media_file_history 
                       WHERE torrent_hash=? AND file_index=?""",
                    (hash, file_id)
                ).fetchone()
            except Exception:
                logger.exception("Could not get previous progress")
                return None

    def save_progress(self, state: PlaybackState):
        with get_connection() as conn:
            try:
                conn.execute(
                    """UPDATE media_file_history
                       SET playback_timecode = ?, audio_track = ?, subtitle_track = ?, is_watched = ?
                       WHERE torrent_hash = ? AND file_index = ?
                    """,
                    (state.timecode, state.audio_track, state.subtitle_track, int(state.is_watched), state.hash, state.file_id)
                )
            except Exception:
                logger.exception("Could not save progress")

    def parse_ep(self, name):
        m = re.search(r'S(\d+)E(\d+)', name, re.IGNORECASE)
        if m: return (1, int(m.group(1)), int(m.group(2)), name)
        m = re.search(r'(\d+)x(\d+)', name, re.IGNORECASE)
        if m: return (1, int(m.group(1)), int(m.group(2)), name)
        return (0, 0, 0, name)