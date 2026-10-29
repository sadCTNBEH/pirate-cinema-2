import json
import logging
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

from backend.core.settings import get_data_dir
from backend.repositories.metadata import MetadataRepository

logger = logging.getLogger(__name__)


def score_poster_url(url: str, preferred_lang: str = "ru") -> float:
    """Calculate ranking score for a poster URL based on size and language preference."""
    if not url:
        return 0.0

    score = 10.0
    url_lower = url.lower()

    # 1. Language preference
    lang = preferred_lang.lower()
    if (
        f"_{lang}" in url_lower
        or f"-{lang}" in url_lower
        or f"/{lang}/" in url_lower
        or f".{lang}." in url_lower
        or (
            lang == "ru"
            and any(
                k in url_lower
                for k in ("russian", "rus", "kinopoisk", "yandex.net", ".ru/")
            )
        )
    ):
        score += 50.0
    elif (
        "_en" in url_lower
        or "-en" in url_lower
        or "/en/" in url_lower
        or ".en." in url_lower
    ):
        score += 20.0

    # 2. Size / Resolution hints in URL
    if any(
        k in url_lower
        for k in (
            "original",
            "untouched",
            "2160",
            "1080",
            "1200",
            "large",
            "max",
            "full",
        )
    ):
        score += 30.0
    elif any(k in url_lower for k in ("medium", "720", "500", "w500", "w780")):
        score += 15.0
    elif any(k in url_lower for k in ("small", "thumb", "300", "w185", "w92")):
        score += 5.0
    else:
        score += 10.0

    return score


def rank_posters(posters: list[str], preferred_lang: str = "ru") -> list[str]:
    """Rank list of poster URLs prioritizing size and preferred language."""
    valid_urls = [p.strip() for p in posters if p and p.strip()]
    if not valid_urls:
        return []

    # Deduplicate preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for u in valid_urls:
        if u not in seen:
            seen.add(u)
            unique.append(u)

    unique.sort(key=lambda u: score_poster_url(u, preferred_lang), reverse=True)
    return unique


def pick_best_poster(posters: list[str], preferred_lang: str = "ru") -> str | None:
    """Pick highest ranked poster URL from candidate list."""
    ranked = rank_posters(posters, preferred_lang)
    return ranked[0] if ranked else None


class MetadataCache:
    """Offline cache layer combining in-memory caching, SQLite persistence, and poster storage with TTL."""

    def __init__(
        self,
        metadata_repo: MetadataRepository | None = None,
        posters_dir: Path | None = None,
        default_ttl: int = 86400 * 7,
    ):
        self._lock = threading.RLock()
        self._repo = metadata_repo
        self._posters_dir = posters_dir or (get_data_dir() / "posters")
        self._default_ttl = default_ttl
        self._mem_cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def age(self, key):
        import time

        with self._lock:
            entry = self._mem_cache.get(key)
            if entry:
                return max(0, int(time.time() - entry[0]))
            return self._repo.cached_metadata_age(key) if self._repo else None

    def get(self, key: str, max_age_seconds: int | None = None):
        with self._lock:
            return self._get(key, max_age_seconds)

    def _get(
        self, key: str, max_age_seconds: int | None = None
    ) -> dict[str, Any] | None:
        """Retrieve cached metadata item by key if within TTL."""
        import time

        clean_key = key.strip()
        ttl = max_age_seconds if max_age_seconds is not None else self._default_ttl

        if ttl <= 0:
            self._mem_cache.pop(clean_key, None)
            return None

        if clean_key in self._mem_cache:
            ts, val = self._mem_cache[clean_key]
            if time.time() - ts <= ttl:
                return val.copy()
            elif time.time() - ts > 86400 * 30:
                self._mem_cache.pop(clean_key, None)

        if self._repo is not None:
            data = self._repo.get_cached_metadata(clean_key, max_age_seconds=ttl)
            if data:
                # Keep the persisted age: reading must never renew the TTL.
                return data

        return None

    def set(self, key, data, imdb_id=None, title=None):
        with self._lock:
            self._set(key, data, imdb_id, title)

    def _set(
        self,
        key: str,
        data: dict[str, Any],
        imdb_id: str | None = None,
        title: str | None = None,
    ) -> None:
        """Store metadata item in offline cache with current timestamp."""
        import time

        clean_key = key.strip()
        if len(json.dumps(data)) > 256 * 1024:
            return
        if len(self._mem_cache) >= 64:
            self._mem_cache.pop(next(iter(self._mem_cache)), None)
        self._mem_cache[clean_key] = (time.time(), data.copy())

        if self._repo is not None:
            try:
                self._repo.save_cached_metadata(
                    clean_key, data, imdb_id=imdb_id, title=title
                )
            except (sqlite3.Error, TypeError, ValueError, OSError) as e:
                logger.warning(
                    "Failed to persist metadata cache for key '%s': %s", clean_key, e
                )

    def get_poster_path(self, identifier: str) -> Path | None:
        """Return local file path if poster is already cached on disk."""
        clean_id = re.sub(r"[^\w\-.]", "", identifier)
        if not clean_id:
            return None

        # Check .jpg and .png
        for ext in (".jpg", ".png", ".webp"):
            p = self._posters_dir / f"{clean_id}{ext}"
            if p.is_file():
                return p
        return None

    def save_poster(self, identifier: str, content: bytes, ext: str = ".jpg") -> Path:
        """Save poster bytes to offline filesystem cache."""
        self._posters_dir.mkdir(parents=True, exist_ok=True)
        clean_id = re.sub(r"[^\w\-.]", "", identifier)
        target = self._posters_dir / f"{clean_id}{ext}"
        target.write_bytes(content)
        return target
