import logging
import re
import sqlite3
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
    """Offline cache layer combining in-memory caching, SQLite persistence, and poster storage."""

    def __init__(
        self,
        metadata_repo: MetadataRepository | None = None,
        posters_dir: Path | None = None,
    ):
        self._repo = metadata_repo
        self._posters_dir = posters_dir or (get_data_dir() / "posters")
        self._mem_cache: dict[str, dict[str, Any]] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        """Retrieve cached metadata item by key."""
        clean_key = key.strip()
        if clean_key in self._mem_cache:
            return self._mem_cache[clean_key].copy()

        if self._repo is not None:
            data = self._repo.get_cached_metadata(clean_key)
            if data:
                self._mem_cache[clean_key] = data.copy()
                return data

        return None

    def set(
        self,
        key: str,
        data: dict[str, Any],
        imdb_id: str | None = None,
        title: str | None = None,
    ) -> None:
        """Store metadata item in offline cache."""
        clean_key = key.strip()
        self._mem_cache[clean_key] = data.copy()

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
