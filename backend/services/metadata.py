import json
import logging
import sqlite3
from pathlib import Path

import anyio
import httpx

from backend.core.settings import get_data_dir
from backend.infrastructure.catalog.cinemeta import clean_title, search_metadata
from backend.repositories import library as library_repo
from backend.repositories import metadata as metadata_repo

logger = logging.getLogger(__name__)


def _write_poster_file(path: Path, content: bytes) -> None:
    path.write_bytes(content)


async def fetch_and_save_metadata(torrent_hash: str, raw_title: str) -> None:
    try:
        has_poster = await anyio.to_thread.run_sync(
            library_repo.has_poster, torrent_hash
        )
        if has_poster:
            return
    except sqlite3.Error as db_err:
        logger.warning("Failed to check poster existence in DB: %s", db_err)
        return

    clean, _ = clean_title(raw_title)
    if not clean:
        return

    try:
        results = await search_metadata(clean)
    except (httpx.HTTPError, ValueError, KeyError) as e:
        logger.warning("Metadata search failed for '%s': %s", clean, e)
        return

    if not results:
        return

    meta = results[0]
    poster_file = ""

    if meta.get("poster_url"):
        try:
            poster_dir = get_data_dir() / "posters"
            poster_dir.mkdir(parents=True, exist_ok=True)
            poster_path = poster_dir / f"{torrent_hash}.jpg"

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(meta["poster_url"])
                response.raise_for_status()
                await anyio.to_thread.run_sync(
                    _write_poster_file, poster_path, response.content
                )
                poster_file = f"{torrent_hash}.jpg"
        except (httpx.HTTPError, OSError) as e:
            logger.warning(
                "Failed to download or save poster for %s: %s", torrent_hash, e
            )

    try:
        await anyio.to_thread.run_sync(
            metadata_repo.save_full_metadata,
            torrent_hash,
            meta.get("title", raw_title),
            meta.get("overview", ""),
            meta.get("year"),
            meta.get("rating", 0.0),
            poster_file,
            json.dumps(meta.get("genres", [])),
        )
    except sqlite3.Error as db_err:
        logger.error(
            "Failed to save metadata to DB for %s: %s", torrent_hash, db_err
        )
