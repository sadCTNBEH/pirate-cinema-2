import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from backend.core.settings import get_data_dir
from backend.infrastructure.catalog.cinemeta import clean_title
from backend.repositories.base import BaseRepository
from backend.repositories.db import Database
from backend.repositories.library import LibraryRepository


class HistoryRepository(BaseRepository):
    def __init__(self, db: Database):
        super().__init__(db)

    def _presentation(self, rows):
        items = [dict(row) for row in rows]
        ids = list({item['imdb_id'] for item in items if item.get('imdb_id')})
        cached = {}
        if ids:
            marks = ','.join('?' for _ in ids)
            with self.connection() as conn:
                metadata = conn.execute(f'SELECT imdb_id, data_json FROM offline_metadata_cache WHERE imdb_id IN ({marks}) ORDER BY created_at DESC', ids).fetchall()
                collections = conn.execute(f'SELECT media_id, title, title_ru, poster_url FROM media_collections WHERE media_id IN ({marks})', ids).fetchall()
            for row in metadata:
                try:
                    data = json.loads(row['data_json'])
                    if isinstance(data, dict):
                        cached.setdefault(row['imdb_id'], data)
                except (ValueError, TypeError):
                    pass
            for row in collections:
                cached.setdefault(row['media_id'], dict(row))
        posters = get_data_dir() / 'posters'
        for item in items:
            imdb = item.get('imdb_id')
            meta = cached.get(imdb, {})
            canonical = meta.get('title_ru') or meta.get('title') or meta.get('name')
            raw = str(item.get('title') or item.get('file_name') or '')
            if not item.get('title'):
                raw = raw.replace('\\', '/').rsplit('/', 1)[-1]
            raw = re.sub(r'(?i)\.(mkv|mp4|avi|webm|m4v)$', '', raw)
            raw = re.split(r'(?i)\bS\d{1,3}E\d{1,3}\b|\b\d{1,2}x\d{1,3}\b', raw)[0]
            title, year = clean_title(raw)
            title = title.strip(' ._-')
            if canonical:
                title = str(canonical).strip()
            item['title'] = title or item.get('title') or item.get('file_name')
            item['year'] = item.get('year') or meta.get('year') or year
            poster = meta.get('poster_local_url') or meta.get('poster_url') or meta.get('poster')
            hash_ = str(item['torrent_hash'])
            if re.fullmatch(r'[a-zA-Z0-9_-]+', hash_) and (posters / f'{hash_}.jpg').is_file():
                poster = f'/api/library/poster/{quote(hash_, safe="")}'
            elif imdb and re.fullmatch(r'tt\d{1,12}', imdb) and (posters / 'catalog' / f'{imdb}.jpg').is_file():
                poster = f'/api/posters/catalog/{imdb}.jpg'
            elif not poster and item.get('poster_file'):
                poster = f'/api/library/poster/{quote(hash_, safe="")}'
            item['poster_url'] = poster if isinstance(poster, str) and poster.startswith(('http://', 'https://', '/')) else None
            context = item.pop('playback_context', None)
            if context:
                try:
                    context = json.loads(context)
                    item['anime_playback'] = context
                    item['title'] = context['title']
                    item['poster_url'] = context.get('poster_url')
                    item['media_type'] = context.get('media_type', 'series')
                    item['year'] = context.get('year')
                except (ValueError, KeyError, TypeError):
                    pass
        return items

    def save_anime_playback(self, context):
        """One title row in the existing history, independent of the chosen site."""
        key = 'online:anime:' + context['media_id']
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute('UPDATE OR IGNORE media_file_history SET torrent_hash=? WHERE torrent_hash=? AND playback_context IS NOT NULL', (key, 'anime:' + context['media_id']))
            conn.execute('DELETE FROM media_file_history WHERE torrent_hash=? AND playback_context IS NOT NULL', ('anime:' + context['media_id'],))
            alias = 'yummy:' + context['source_title_id'] if context['source'] == 'yummy' else context['media_id']
            if alias != context['media_id']:
                conn.execute('DELETE FROM media_file_history WHERE torrent_hash=? AND file_index=0', ('online:anime:' + alias,))
                conn.execute('INSERT OR IGNORE INTO media_episode_history (title_id,season,episode,is_watched,updated_at) SELECT ?,season,episode,is_watched,updated_at FROM media_episode_history WHERE title_id=?', (context['media_id'],alias))
                conn.execute('DELETE FROM media_episode_history WHERE title_id=?', (alias,))
            previous = conn.execute('SELECT season, episode, playback_timecode, playback_duration FROM media_file_history WHERE torrent_hash=? AND file_index=0', (key,)).fetchone()
            same_episode = previous and previous['season'] == context['season'] and previous['episode'] == context['episode']
            conn.execute('''INSERT INTO media_file_history
                (torrent_hash, file_index, file_name, first_played_at, last_played_at, season, episode, imdb_id, playback_context, playback_timecode, playback_duration)
                VALUES (?,0,?,?,?,?,?,?,?,?,?) ON CONFLICT(torrent_hash,file_index) DO UPDATE SET
                file_name=excluded.file_name, last_played_at=excluded.last_played_at,
                season=excluded.season, episode=excluded.episode, imdb_id=excluded.imdb_id,
                playback_context=excluded.playback_context, playback_timecode=excluded.playback_timecode,
                playback_duration=excluded.playback_duration, is_watched=CASE WHEN media_file_history.season=excluded.season AND media_file_history.episode=excluded.episode THEN media_file_history.is_watched ELSE 0 END, launch_count=launch_count+1''',
                (key, context['source'], now, now, context['season'], context['episode'], context['media_id'],
                 json.dumps(context, ensure_ascii=False), previous['playback_timecode'] if same_episode else 0,
                 previous['playback_duration'] if same_episode else 0))
        return self.get_file_entry(key, 0)

    def mark_played(
        self,
        torrent_hash: str,
        file_index: int,
        file_name: str,
        file_path: str | None = None,
        season: int | None = None,
        episode: int | None = None,
        imdb_id: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat() + "Z"
        if season is None or episode is None:
            parsed = LibraryRepository.parse_ep(file_name)
            if parsed[0] == 1:
                season = parsed[1]
                episode = parsed[2]

        with self.connection() as conn:
            if not imdb_id:
                row = conn.execute(
                    "SELECT imdb_id FROM media_metadata WHERE torrent_hash = ?",
                    (torrent_hash,),
                ).fetchone()
                if row and row["imdb_id"]:
                    imdb_id = str(row["imdb_id"])

            conn.execute(
                """
                INSERT INTO media_file_history (
                    torrent_hash, file_index, file_name, file_path, first_played_at,
                    last_played_at, launch_count, season, episode, imdb_id
                )
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT(torrent_hash, file_index) DO UPDATE SET
                    last_played_at = excluded.last_played_at,
                    launch_count = launch_count + 1,
                    season = COALESCE(excluded.season, media_file_history.season),
                    episode = COALESCE(excluded.episode, media_file_history.episode),
                    imdb_id = COALESCE(excluded.imdb_id, media_file_history.imdb_id)
            """,
                (
                    torrent_hash,
                    file_index,
                    file_name,
                    file_path,
                    now,
                    now,
                    season,
                    episode,
                    imdb_id,
                ),
            )

    def update_progress(
        self,
        torrent_hash: str,
        file_index: int,
        timecode: int,
        duration: int,
        audio_track: int = 0,
    ) -> None:
        tc = max(0, int(timecode))
        dur = max(0, int(duration))
        if dur > 0 and tc > dur:
            tc = dur
        is_watched = (
            1
            if dur > 0 and ((dur - tc) <= 180 or (tc / dur) >= 0.90)
            else 0
        )
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE media_file_history
                SET playback_timecode = ?, playback_duration = ?,
                    is_watched = CASE WHEN is_watched = 1 THEN 1 ELSE ? END,
                    audio_track = CASE WHEN ? > 0 THEN ? ELSE audio_track END
                WHERE torrent_hash = ? AND file_index = ?
            """,
                (
                    tc,
                    dur,
                    is_watched,
                    audio_track,
                    audio_track,
                    torrent_hash,
                    file_index,
                ),
            )

    def list_history(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT (h.torrent_hash || ':' || h.file_index) AS id,
                       h.torrent_hash, h.file_index, h.file_name, h.file_path,
                       h.playback_timecode, h.playback_duration, h.is_watched,
                       h.season, h.episode, COALESCE(h.imdb_id, m.imdb_id) AS imdb_id,
                       h.last_played_at, h.playback_context, m.title, m.poster_file, m.year, t.media_type
                FROM media_file_history h
                LEFT JOIN media_metadata m ON h.torrent_hash = m.torrent_hash
                LEFT JOIN media_types t ON h.torrent_hash = t.torrent_hash
                WHERE (h.torrent_hash NOT LIKE 'online:%' OR h.playback_context IS NOT NULL)
                ORDER BY h.last_played_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return self._presentation(rows)

    def list_continue_watching(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT (h.torrent_hash || ':' || h.file_index) AS id,
                       h.torrent_hash, h.file_index, h.file_name, h.file_path,
                       h.playback_timecode, h.playback_duration, h.is_watched,
                       h.season, h.episode, COALESCE(h.imdb_id, m.imdb_id) AS imdb_id,
                       h.last_played_at, h.playback_context, m.title, m.poster_file, m.year, t.media_type
                FROM media_file_history h
                LEFT JOIN media_metadata m ON h.torrent_hash = m.torrent_hash
                LEFT JOIN media_types t ON h.torrent_hash = t.torrent_hash
                WHERE h.launch_count > 0 AND h.is_watched = 0 AND (h.playback_timecode > 0 OR h.playback_context IS NOT NULL) AND (h.torrent_hash NOT LIKE 'online:%' OR h.playback_context IS NOT NULL)
                ORDER BY h.last_played_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        items: list[dict[str, Any]] = []
        for d in self._presentation(rows):
            tc = d.get("playback_timecode") or 0
            dur = d.get("playback_duration") or 0
            d["position_seconds"] = float(tc)
            d["duration_seconds"] = float(dur) if dur > 0 else None
            d["watched"] = bool(d.get("is_watched"))
            d["title_id"] = d.get("imdb_id") or d.get("torrent_hash")
            d["infohash"] = d.get("torrent_hash")
            items.append(d)
        return items

    def get_file_entry(
        self, torrent_hash: str, file_index: int
    ) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT (h.torrent_hash || ':' || h.file_index) AS id,
                       h.torrent_hash, h.file_index, h.file_name, h.file_path,
                       h.playback_timecode, h.playback_duration, h.is_watched,
                       h.season, h.episode, COALESCE(h.imdb_id, m.imdb_id) AS imdb_id,
                       h.last_played_at, h.playback_context, m.title, m.poster_file, m.year, t.media_type
                FROM media_file_history h
                LEFT JOIN media_metadata m ON h.torrent_hash = m.torrent_hash
                LEFT JOIN media_types t ON h.torrent_hash = t.torrent_hash
                WHERE h.torrent_hash = ? AND h.file_index = ?
                """,
                (torrent_hash, file_index),
            ).fetchone()
            if row:
                return self._presentation([row])[0]
        return None

    def mark_watched(
        self, torrent_hash: str, file_index: int, watched: bool = True
    ) -> bool:
        now = datetime.now(timezone.utc).isoformat() + "Z"
        with self.connection() as conn:
            if watched:
                cursor = conn.execute(
                    """
                    UPDATE media_file_history
                    SET is_watched = 1,
                        playback_timecode = CASE
                            WHEN playback_duration > 0 THEN playback_duration
                            ELSE playback_timecode
                        END,
                        last_played_at = ?
                    WHERE torrent_hash = ? AND file_index = ?
                    """,
                    (now, torrent_hash, file_index),
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE media_file_history
                    SET is_watched = 0,
                        playback_timecode = 0,
                        last_played_at = ?
                    WHERE torrent_hash = ? AND file_index = ?
                    """,
                    (now, torrent_hash, file_index),
                )

            # If this file has season & episode, also update episode state
            file_row = conn.execute(
                "SELECT season, episode, imdb_id FROM media_file_history WHERE torrent_hash = ? AND file_index = ?",
                (torrent_hash, file_index),
            ).fetchone()
            if file_row and file_row["season"] is not None and file_row["episode"] is not None:
                title_id = file_row["imdb_id"] or torrent_hash
                s = int(file_row["season"])
                e = int(file_row["episode"])
                conn.execute(
                    """
                    INSERT INTO media_episode_history (title_id, season, episode, is_watched, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(title_id, season, episode) DO UPDATE SET
                        is_watched = excluded.is_watched,
                        updated_at = excluded.updated_at
                    """,
                    (title_id, s, e, 1 if watched else 0, now),
                )

        return cursor.rowcount > 0

    def mark_episode_watched(
        self,
        title_id: str,
        season: int,
        episode: int,
        watched: bool = True,
    ) -> bool:
        now = datetime.now(timezone.utc).isoformat() + "Z"
        status_val = 1 if watched else 0
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO media_episode_history (title_id, season, episode, is_watched, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(title_id, season, episode) DO UPDATE SET
                    is_watched = excluded.is_watched,
                    updated_at = excluded.updated_at
                """,
                (title_id, season, episode, status_val, now),
            )

            # Also update any physical files in media_file_history matching this title & season/episode
            if watched:
                conn.execute(
                    """
                    UPDATE media_file_history
                    SET is_watched = 1,
                        playback_timecode = CASE
                            WHEN playback_duration > 0 THEN playback_duration
                            ELSE playback_timecode
                        END,
                        last_played_at = ?
                    WHERE (imdb_id = ? OR torrent_hash = ?)
                      AND season = ? AND episode = ?
                    """,
                    (now, title_id, title_id, season, episode),
                )
            else:
                conn.execute(
                    """
                    UPDATE media_file_history
                    SET is_watched = 0,
                        playback_timecode = 0,
                        last_played_at = ?
                    WHERE (imdb_id = ? OR torrent_hash = ?)
                      AND season = ? AND episode = ?
                    """,
                    (now, title_id, title_id, season, episode),
                )

        return True

    def get_watched_episodes_map(
        self, title_id: str, season: int | None = None
    ) -> set[tuple[int, int]]:
        watched_set: set[tuple[int, int]] = set()
        with self.connection() as conn:
            # 1. From media_episode_history
            if season is not None:
                rows_ep = conn.execute(
                    """
                    SELECT season, episode FROM media_episode_history
                    WHERE title_id = ? AND season = ? AND is_watched = 1
                    """,
                    (title_id, season),
                ).fetchall()
            else:
                rows_ep = conn.execute(
                    """
                    SELECT season, episode FROM media_episode_history
                    WHERE title_id = ? AND is_watched = 1
                    """,
                    (title_id,),
                ).fetchall()
            for r in rows_ep:
                watched_set.add((int(r["season"]), int(r["episode"])))

            # 2. From media_file_history
            if season is not None:
                rows_file = conn.execute(
                    """
                    SELECT season, episode FROM media_file_history
                    WHERE (imdb_id = ? OR torrent_hash = ?)
                      AND season = ? AND is_watched = 1
                    """,
                    (title_id, title_id, season),
                ).fetchall()
            else:
                rows_file = conn.execute(
                    """
                    SELECT season, episode FROM media_file_history
                    WHERE (imdb_id = ? OR torrent_hash = ?)
                      AND season IS NOT NULL AND episode IS NOT NULL AND is_watched = 1
                    """,
                    (title_id, title_id),
                ).fetchall()
            for r in rows_file:
                if r["season"] is not None and r["episode"] is not None:
                    watched_set.add((int(r["season"]), int(r["episode"])))

        return watched_set

    def delete_entry(self, torrent_hash: str, file_index: int) -> bool:
        with self.connection() as conn:
            entry = conn.execute(
                """
                SELECT season, episode, imdb_id, is_watched
                FROM media_file_history
                WHERE torrent_hash = ? AND file_index = ?
                """,
                (torrent_hash, file_index),
            ).fetchone()

            cursor = conn.execute(
                "DELETE FROM media_file_history WHERE torrent_hash = ? AND file_index = ?",
                (torrent_hash, file_index),
            )
            deleted = cursor.rowcount > 0

            # If entry had season/episode, recheck logical episode state
            if deleted and entry and entry["season"] is not None and entry["episode"] is not None:
                s = int(entry["season"])
                e = int(entry["episode"])
                title_id = entry["imdb_id"] or torrent_hash

                remaining_watched = conn.execute(
                    """
                    SELECT 1 FROM media_file_history
                    WHERE (imdb_id = ? OR torrent_hash = ?)
                      AND season = ? AND episode = ? AND is_watched = 1
                    LIMIT 1
                    """,
                    (title_id, title_id, s, e),
                ).fetchone()

                if not remaining_watched:
                    # Remove from media_episode_history so deleted file doesn't leave false watched state
                    conn.execute(
                        """
                        DELETE FROM media_episode_history
                        WHERE (title_id = ? OR title_id = ?) AND season = ? AND episode = ?
                        """,
                        (title_id, torrent_hash, s, e),
                    )

        return deleted
