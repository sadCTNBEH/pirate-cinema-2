import asyncio
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import anyio
import httpx

from backend.core.settings import get_data_dir
from backend.exceptions import ExternalServiceError, NotFoundError
from backend.infrastructure.catalog.cache import (
    MetadataCache,
    pick_best_poster,
    rank_posters,
)
from backend.infrastructure.catalog.cinemeta import (
    CinemetaProvider,
    clean_title,
    title_candidates,
)
from backend.infrastructure.catalog.tvmaze import TVmazeProvider
from backend.infrastructure.catalog.wikidata import WikidataProvider
from backend.repositories.library import LibraryRepository
from backend.repositories.metadata import MetadataRepository
from backend.services.i18n import t

logger = logging.getLogger(__name__)


def _write_poster_file(path: Path, content: bytes) -> None:
    path.write_bytes(content)


class MetadataService:
    """Multi-provider metadata orchestration service with offline cache and localized labels."""

    def __init__(
        self,
        metadata_repo: MetadataRepository,
        library_repo: LibraryRepository,
        catalog_client: Any = None,
        posters_dir: Path | None = None,
        cache: MetadataCache | None = None,
        cinemeta_provider: CinemetaProvider | None = None,
        tvmaze_provider: TVmazeProvider | None = None,
        wikidata_provider: WikidataProvider | None = None,
    ):
        self._metadata_repo = metadata_repo
        self._library_repo = library_repo
        self._catalog = catalog_client
        self._posters_dir = posters_dir or (get_data_dir() / "posters")
        self._cache = cache or MetadataCache(
            metadata_repo=metadata_repo, posters_dir=self._posters_dir
        )

        # Multi-provider chain: Cinemeta -> TVmaze (fallback) -> Wikidata (RU labels)
        if cinemeta_provider is not None:
            self._cinemeta = cinemeta_provider
        elif catalog_client is not None:
            self._cinemeta = catalog_client
        else:
            self._cinemeta = CinemetaProvider()

        self._tvmaze = tvmaze_provider or TVmazeProvider()
        self._wikidata = wikidata_provider or WikidataProvider()
        self._background_tasks: set[asyncio.Task] = set()

    @property
    def cache(self) -> MetadataCache:
        return self._cache

    async def popular_movies(self) -> list[dict[str, Any]]:
        cache_key = "popular:movies"
        cached = self._cache.get(cache_key)
        if cached and isinstance(cached.get("items"), list):
            return cached["items"]

        try:
            items = await self._cinemeta.popular()
            if items:
                self._cache.set(cache_key, {"items": items})
            return items
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
        cache_key = "popular:series"
        cached = self._cache.get(cache_key)
        if cached and isinstance(cached.get("items"), list):
            return cached["items"]

        try:
            items = await self._cinemeta.popular_series()
            if items:
                self._cache.set(cache_key, {"items": items})
            return items
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
        """Fetch details for movie/series by IMDB id.

        Flow: cache -> Cinemeta -> TVmaze (fallback) -> Wikidata RU labels -> merge -> cache -> return.
        """
        clean_id = imdb_id.strip()
        cache_key = f"meta:{clean_id}"

        # 1. Check offline cache
        cached = self._cache.get(cache_key)
        if cached:
            logger.debug("Offline cache hit for %s", cache_key)
            return cached

        meta: dict[str, Any] | None = None

        # 2. Query Cinemeta (Primary)
        try:
            if hasattr(self._cinemeta, "lookup"):
                meta = await self._cinemeta.lookup(clean_id, media_type)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
            logger.warning("Cinemeta lookup failed for %s: %s", clean_id, e)

        # 3. Fallback to TVmaze if Cinemeta returned nothing
        if not meta:
            try:
                tvm = await self._tvmaze.lookup(clean_id)
                if tvm:
                    meta = tvm
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
                logger.warning("TVmaze fallback lookup failed for %s: %s", clean_id, e)

        if not meta:
            raise NotFoundError(t("err_not_found"))

        # 4. Enrich with Wikidata Russian labels (RU labels prioritized)
        try:
            wiki = await self._wikidata.lookup_by_imdb(clean_id)
            if wiki:
                title_ru = wiki.get("title_ru")
                overview_ru = wiki.get("overview_ru")
                if title_ru:
                    meta["title_ru"] = title_ru
                    meta["original_title"] = meta.get("original_title") or meta.get(
                        "title"
                    )
                    meta["title"] = title_ru  # Prioritize Russian title
                if overview_ru:
                    meta["overview_ru"] = overview_ru
                meta["source"] = f"{meta.get('source', 'catalog')}+wikidata"
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
            logger.debug("Wikidata enrichment failed for %s: %s", clean_id, e)

        # 5. Poster ranking
        candidates = [meta.get("poster_url")]
        best_poster = pick_best_poster(candidates, preferred_lang="ru")
        if best_poster:
            meta["poster_url"] = best_poster

        # 6. Save to offline cache
        self._cache.set(cache_key, meta, imdb_id=clean_id, title=meta.get("title"))
        return meta

    async def search_catalog(
        self, query: str, type_: str = "movie"
    ) -> list[dict[str, Any]]:
        """Search catalog with offline cache, multi-provider fallback, and RU localization."""
        clean_q = query.strip()
        if not clean_q:
            return []

        cache_key = f"search:{type_}:{clean_q.lower()}"
        cached = self._cache.get(cache_key)
        if cached and isinstance(cached.get("items"), list):
            return cached["items"]

        results: list[dict[str, Any]] = []

        # 1. Search Cinemeta
        try:
            if hasattr(self._cinemeta, "search"):
                results = await self._cinemeta.search(clean_q, type_)
            elif hasattr(self._cinemeta, "search_metadata"):
                results = await self._cinemeta.search_metadata(clean_q, type_)
            elif hasattr(self._cinemeta, "search_catalog"):
                results = await self._cinemeta.search_catalog(clean_q)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
            logger.warning("Cinemeta search failed for '%s': %s", clean_q, e)

        # 2. Fallback to TVmaze if Cinemeta returned empty
        if not results:
            try:
                results = await self._tvmaze.search(clean_q)
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
                logger.warning("TVmaze search failed for '%s': %s", clean_q, e)

        # 3. Enrich top results with Wikidata RU labels
        for r in results[:4]:
            r_id = r.get("id", "")
            if r_id.startswith("tt"):
                try:
                    wiki = await self._wikidata.lookup_by_imdb(r_id)
                    if wiki and wiki.get("title_ru"):
                        r["title_ru"] = wiki["title_ru"]
                        r["original_title"] = r.get("original_title") or r.get("title")
                        r["title"] = wiki["title_ru"]
                        if wiki.get("overview_ru"):
                            r["overview_ru"] = wiki["overview_ru"]
                except (httpx.HTTPError, KeyError, ValueError, TypeError) as wiki_err:
                    logger.debug(
                        "Wikidata label lookup failed for %s: %s", r_id, wiki_err
                    )

        self._cache.set(cache_key, {"items": results}, title=clean_q)
        return results

    # Alias for router compatibility
    search_movie_meta = search_catalog

    async def streams(
        self, imdb_id: str, media_type: str = "movie"
    ) -> list[dict[str, Any]]:
        try:
            if hasattr(self._cinemeta, "streams"):
                return await self._cinemeta.streams(imdb_id, media_type)
            return []
        except httpx.HTTPStatusError as e:
            logger.error("Catalog streams status error for %s: %s", imdb_id, e)
            raise ExternalServiceError(
                f"Catalog streams error: {e.response.status_code}",
                status_code=502,
            ) from e
        except httpx.RequestError as e:
            logger.error("Catalog streams connection error for %s: %s", imdb_id, e)
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
            logger.warning("Timed out waiting for metadata tasks to finish on shutdown")
        finally:
            self._background_tasks.clear()

    async def fetch_and_save_metadata(self, torrent_hash: str, raw_title: str) -> None:
        try:
            has_poster = await anyio.to_thread.run_sync(
                self._library_repo.has_poster, torrent_hash
            )
            if has_poster:
                return
            # If metadata was already fully fetched (title/overview exist) but poster failed,
            # try downloading poster again but skip expensive search/API calls
            has_meta = await anyio.to_thread.run_sync(
                self._library_repo.has_full_metadata, torrent_hash
            )
        except sqlite3.Error as db_err:
            logger.warning("Failed to check metadata existence in DB: %s", db_err)
            return

        if has_meta:
            # Metadata fetched but poster missing — retry poster download only
            logger.debug(
                "Metadata already fetched for %s, retrying poster download only", torrent_hash
            )
            # We have the metadata but no poster; skip re-searching and just return
            # (poster will be attempted again next time library is loaded)
            return

        clean_fn = getattr(self._catalog, "clean_title", clean_title)
        clean, _ = clean_fn(raw_title)
        if not clean:
            return

        candidates = title_candidates(raw_title)
        if clean not in candidates:
            candidates.append(clean)

        results = []
        for cand in candidates:
            try:
                results = await self.search_catalog(cand)
                if results:
                    break
            except (httpx.HTTPError, ValueError, KeyError) as e:
                logger.debug("Metadata search failed for '%s': %s", cand, e)

        if not results:
            return

        meta = results[0]
        poster_file = ""

        # Collect and rank poster candidates
        raw_candidates: list[str] = []
        for r in results:
            if isinstance(r, dict):
                p = r.get("poster_url") or r.get("poster")
                if p:
                    raw_candidates.append(p)
                bg = r.get("background_url")
                if bg:
                    raw_candidates.append(bg)

        candidate_urls = rank_posters(raw_candidates, preferred_lang="ru")
        last_error: Exception | None = None

        if candidate_urls:
            self._posters_dir.mkdir(parents=True, exist_ok=True)
            poster_path = self._posters_dir / f"{torrent_hash}.jpg"
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            }

            failed_urls: list[str] = []
            try:
                async with httpx.AsyncClient(
                    timeout=10.0, follow_redirects=True, headers=headers
                ) as client:
                    for cand_url in candidate_urls:
                        cand_url = cand_url.strip()
                        if cand_url.startswith("//"):
                            cand_url = f"https:{cand_url}"
                        elif not cand_url.startswith(("http://", "https://")):
                            cand_url = f"https://{cand_url}"

                        try:
                            response = await client.get(cand_url)
                            response.raise_for_status()
                            if len(response.content) < 100:
                                failed_urls.append(f"{cand_url} (too small)")
                                continue
                            await anyio.to_thread.run_sync(
                                _write_poster_file, poster_path, response.content
                            )
                            poster_file = f"{torrent_hash}.jpg"
                            break
                        except (httpx.HTTPError, OSError) as e:
                            failed_urls.append(f"{cand_url}: {e}")
                            logger.debug(
                                "Candidate poster download failed for '%s': %s",
                                cand_url,
                                e,
                            )
            except (httpx.HTTPError, OSError) as e:
                failed_urls.append(str(e))

            if not poster_file:
                logger.warning(
                    "Failed to download poster for %s — tried %d URL(s): %s",
                    torrent_hash,
                    len(failed_urls),
                    failed_urls[0] if failed_urls else "no candidates",
                )
        else:
            logger.debug(
                "No poster URL candidates found for %s (title: %s), skipping download",
                torrent_hash,
                raw_title[:60],
            )

        try:
            await anyio.to_thread.run_sync(
                self._metadata_repo.save_full_metadata,
                torrent_hash,
                meta.get("title_ru") or meta.get("title", raw_title),
                meta.get("overview", ""),
                meta.get("year"),
                meta.get("rating", 0.0),
                poster_file,
                json.dumps(meta.get("genres", [])),
                meta.get("overview_ru"),
            )
        except sqlite3.Error as db_err:
            logger.error(
                "Failed to save metadata to DB for %s: %s",
                torrent_hash,
                db_err,
            )
