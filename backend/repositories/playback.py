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
        name = str(name or "")

        def natural_key(text):
            return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', text)]

        base_sort_name = natural_key(name)

        # 1. S01E05, S1 E5, S01.E05, S01_E05
        # [\.\-\s_]* означает "любое количество точек, тире, пробелов или подчеркиваний между S и E"
        m = re.search(r'S(\d+)[\.\-\s_]*E(\d+)', name, re.IGNORECASE)
        if m:
            return (1, int(m.group(1)), int(m.group(2)), base_sort_name)

        # 2. 1x05, 01x05
        m = re.search(r'(\d+)x(\d+)', name, re.IGNORECASE)
        if m:
            return (1, int(m.group(1)), int(m.group(2)), base_sort_name)

        # 3. Episode 05, Ep 05, E05, Ep.5, E 5
        # (?: ... ) - это группа, которую мы не запоминаем, нам важно только число в конце
        m = re.search(r'(?:Episode|Ep|E)[\.\-\s_]*(\d+)', name, re.IGNORECASE)
        if m:
            # Так как сезон не указан, дефолтим к 1 сезону (1, 1, номер_серии)
            return (1, 1, int(m.group(1)), base_sort_name)

        # 4. Фильмы или неизвестный формат
        return (0, 0, 0, base_sort_name)

    def get_state(self, hash, file_id):
        with get_connection() as conn:
            try:
                return conn.execute(
                    """SELECT playback_timecode, is_watched, audio_track, subtitle_track, playback_duration
                       FROM media_file_history 
                       WHERE torrent_hash=? AND file_index=?""",
                    (hash, file_id)
                ).fetchone()
            except Exception:
                logger.exception("Could not get previous progress")
                return None