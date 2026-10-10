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
from backend.repositories.library import LibraryRepository
from backend.repositories.metadata import MetadataRepository
from backend.services.i18n import t

logger = logging.getLogger(__name__)


def _write_poster_file(path: Path, content: bytes) -> None:
    path.write_bytes(content)


class MetadataService:
    def __init__(
        self,
        metadata_repo: MetadataRepository,
        library_repo: LibraryRepository,
        catalog_client: Any,
        posters_dir: Optional[Path] = None,
    ):
        self._metadata_repo = metadata_repo
        self._library_repo = library_repo
        self._catalog = catalog_client
        self._posters_dir = posters_dir or (get_data_dir() / "posters")
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
                f"Catalog metadata lookup error: {e.response.status_code}",
                status_code=502,
            ) from e
        except httpx.RequestError as e:
            logger.error(
                "Catalog metadata lookup connection error for %s: %s",
                imdb_id,
                e,
            )
            raise ExternalServiceError(
                f"Catalog metadata lookup connection error: {e}",
                status_code=502,
            ) from e

        if not meta:
            raise NotFoundError(t("err_not_found"))
        return meta

    async def search_catalog(self, query: str) -> list[dict[str, Any]]:
        try:
            return await self._catalog.search_catalog(query)
        except httpx.HTTPStatusError as e:
            logger.error("Catalog search status error for %s: %s", query, e)
            raise ExternalServiceError(
                f"Catalog search error: {e.response.status_code}",
                status_code=502,
            ) from e
        except httpx.RequestError as e:
            logger.error("Catalog search connection error for %s: %s", query, e)
            raise ExternalServiceError(
                f"Catalog search connection error: {e}", status_code=502
            ) from e

    async def streams(
        self, imdb_id: str, media_type: str = "movie"
    ) -> list[dict[str, Any]]:
        try:
            return await self._catalog.streams(imdb_id, media_type)
        except httpx.HTTPStatusError as e:
            logger.error("Catalog streams status error for %s: %s", imdb_id, e)
            raise ExternalServiceError(
                f"Catalog streams error: {e.response.status_code}",
                status_code=502,
            ) from e
        except httpx.RequestError as e:
            logger.error(
                "Catalog streams connection error for %s: %s", imdb_id, e
            )
            raise ExternalServiceError(
                f"Catalog streams connection error: {e}", status_code=502
            ) from e

    def trigger_metadata_fetch(self, torrent_hash: str, raw_title: str) -> None:
        task = asyncio.create_task(
            self.fetch_and_save_metadata(torrent_hash, raw_title)
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def shutdown(self, timeout: float = 5.0) -> None:
        """Wait for all pending background tasks to complete during graceful shutdown."""
        if not self._background_tasks:
            return
        logger.info(
            "Awaiting %d background metadata tasks on shutdown...",
            len(self._background_tasks),
        )
        try:
            await asyncio.wait_for(
                asyncio.gather(*self._background_tasks, return_exceptions=True),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Timed out waiting for metadata tasks to finish on shutdown"
            )
        finally:
            self._background_tasks.clear()

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
                self._posters_dir.mkdir(parents=True, exist_ok=True)
                poster_path = self._posters_dir / f"{torrent_hash}.jpg"

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
