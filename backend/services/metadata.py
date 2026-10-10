import asyncio
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Optional

import anyio
import httpx

from backend.core.settings import get_data_dir
from backend.exceptions import ExternalServiceError, NotFoundError
from backend.infrastructure.catalog import cinemeta
from backend.repositories.library import LibraryRepository
from backend.repositories.metadata import MetadataRepository
from backend.services.i18n import t

logger = logging.getLogger(__name__)


def _write_poster_file(path: Path, content: bytes) -> None:
    path.write_bytes(content)


class MetadataService:
    def __init__(
        self,
        metadata_repo: Optional[MetadataRepository] = None,
        library_repo: Optional[LibraryRepository] = None,
        catalog_client: Any = None,
    ):
        self._metadata_repo = metadata_repo or MetadataRepository()
        self._library_repo = library_repo or LibraryRepository()
        self._catalog = catalog_client or cinemeta
        self._background_tasks: set[asyncio.Task] = set()

    async def popular_movies(self) -> list[dict[str, Any]]:
        try:
            return await self._catalog.popular()
        except httpx.HTTPStatusError as e:
            logger.error("Catalog API returned status error: %s", e)
            raise ExternalServiceError(
                f"Catalog service error: {e.response.status_code}",
                status_code=502,
            ) from e
        except httpx.RequestError as e:
            logger.error("Catalog connection error: %s", e)
            raise ExternalServiceError(
                f"Catalog network error: {e}", status_code=502
            ) from e

    async def popular_series(self) -> list[dict[str, Any]]:
        try:
            return await self._catalog.popular_series()
        except httpx.HTTPStatusError as e:
            logger.error("Catalog API returned status error for series: %s", e)
            raise ExternalServiceError(
                f"Catalog service error: {e.response.status_code}",
                status_code=502,
            ) from e
        except httpx.RequestError as e:
            logger.error("Catalog connection error for series: %s", e)
            raise ExternalServiceError(
                f"Catalog network error: {e}", status_code=502
            ) from e

    async def movie_meta(
        self, imdb_id: str, media_type: str = "movie"
    ) -> dict[str, Any]:
        try:
            meta = await self._catalog.lookup(imdb_id, media_type)
        except httpx.HTTPStatusError as e:
            logger.error(
                "Catalog metadata lookup status error for %s: %s", imdb_id, e
            )
            raise ExternalServiceError(
                f"Catalog service error: {e.response.status_code}",
                status_code=502,
            ) from e
        except httpx.RequestError as e:
            logger.error(
                "Catalog connection error during lookup for %s: %s", imdb_id, e
            )
            raise ExternalServiceError(
                f"Catalog network error: {e}", status_code=502
            ) from e

        if not meta:
            raise NotFoundError(t("err_not_found"))
        return meta

    async def search_movie_meta(
        self, query: str, media_type: str = "movie"
    ) -> list[dict[str, Any]]:
        try:
            candidates = self._catalog.title_candidates(query) or [query]
            for candidate in candidates:
                results = await self._catalog.search_metadata(candidate, media_type)
                if results:
                    return results
            return []
        except httpx.HTTPStatusError as e:
            logger.error(
                "Catalog search status error for query '%s': %s", query, e
            )
            raise ExternalServiceError(
                f"Catalog search error: {e.response.status_code}",
                status_code=502,
            ) from e
        except httpx.RequestError as e:
            logger.error(
                "Catalog connection error during search for query '%s': %s",
                query,
                e,
            )
            raise ExternalServiceError(
                f"Catalog network error: {e}", status_code=502
            ) from e

    def trigger_metadata_fetch(self, torrent_hash: str, raw_title: str) -> None:
        task = asyncio.create_task(
            self.fetch_and_save_metadata(torrent_hash, raw_title)
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def fetch_and_save_metadata(
        self, torrent_hash: str, raw_title: str
    ) -> None:
        try:
            has_poster = await anyio.to_thread.run_sync(
                self._library_repo.has_poster, torrent_hash
            )
            if has_poster:
                return
        except sqlite3.Error as db_err:
            logger.warning("Failed to check poster existence in DB: %s", db_err)
            return

        clean, _ = self._catalog.clean_title(raw_title)
        if not clean:
            return

        try:
            results = await self._catalog.search_metadata(clean)
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
                    "Failed to download or save poster for %s: %s",
                    torrent_hash,
                    e,
                )

        try:
            await anyio.to_thread.run_sync(
                self._metadata_repo.save_full_metadata,
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
                "Failed to save metadata to DB for %s: %s",
                torrent_hash,
                db_err,
            )


# Функции модуля для обратной совместимости
_default_metadata_service = MetadataService()
fetch_and_save_metadata = _default_metadata_service.fetch_and_save_metadata
