import asyncio
import json
import logging
import sqlite3
import time
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
from backend.infrastructure.catalog.enrich import (
    get_popular_movies,
    get_popular_series,
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
        self._refresh_tasks: dict[str, asyncio.Task] = {}
        self._retry_after: dict[str, float] = {}
        self._cache_generation = 0

    @property
    def cache(self) -> MetadataCache:
        return self._cache

    async def cache_is_fresh(self, kind, language="ru", imdb_id=None, media_type="movie", data=None):
        if imdb_id is not None:
            return await asyncio.to_thread(self._cached, self._meta_key(imdb_id, media_type, language), None, media_type,
                                           f"meta:{imdb_id}" if language == "ru" and media_type == "series" else None) is not None
        from backend.infrastructure.catalog.enrich import (
            _active_background_tasks,
            load_catalog_cache,
        )
        stem = "popular-series" if kind == "series" else "popular"
        path = get_data_dir() / "catalog" / f"{stem}{'-en' if language == 'en' else ''}.json"
        pending = _active_background_tasks.get(str(path.resolve()))
        cached = await asyncio.to_thread(load_catalog_cache, path)
        return cached is not None and not (pending and not pending.done()) and (data is None or cached == data)

    async def cache_age(self, kind, language="ru", imdb_id=None, media_type="movie"):
        def read():
            if imdb_id is not None:
                age = self._cache.age(self._meta_key(imdb_id, media_type, language))
                if age is None and language == "ru" and media_type == "series":
                    age = self._cache.age(f"meta:{imdb_id}")
                return age or 0
            stem = "popular-series" if kind == "series" else "popular"
            path = get_data_dir() / "catalog" / f"{stem}{'-en' if language == 'en' else ''}.json"
            try:
                return max(0, int(time.time() - float(json.loads(path.read_text(encoding="utf-8"))["updated_at"])))
            except (OSError, ValueError, KeyError, TypeError):
                return 0
        return await asyncio.to_thread(read)

    @staticmethod
    def _meta_key(imdb_id, media_type, language):
        return f"meta:{imdb_id}" if media_type == "movie" and language == "ru" else f"meta:{media_type}:{language}:{imdb_id}"

    async def popular_movies(self, language="ru", refresh=False) -> list[dict[str, Any]]:
        try:
            return await get_popular_movies(
                cinemeta_provider=self._cinemeta, wikidata_provider=self._wikidata,
                posters_dir=self._posters_dir / "catalog", background=not refresh, language=language, wait_for_refresh=refresh)
        except httpx.HTTPError as error:
            raise ExternalServiceError("Catalog refresh failed", status_code=503) from error

    async def popular_series(self, language="ru", refresh=False) -> list[dict[str, Any]]:
        try:
            return await get_popular_series(
                cinemeta_provider=self._cinemeta, wikidata_provider=self._wikidata,
                posters_dir=self._posters_dir / "catalog", background=not refresh, language=language, wait_for_refresh=refresh)
        except httpx.HTTPError as error:
            raise ExternalServiceError("Catalog refresh failed", status_code=503) from error

    def _cached(self, key, age=None, expected_type=None, legacy_key=None):
        data = self._cache.get(key, age)
        if data is not None and (not expected_type or not data.get("type") or data["type"] == expected_type):
            return data
        if legacy_key:
            legacy = self._cache.get(legacy_key, age)
            if legacy and legacy.get("type") == expected_type:
                return legacy
        return None

    async def _swr(self, key, fetch, *, refresh=False, imdb_id=None, title=None, expected_type=None, legacy_key=None):
        generation = self._cache_generation
        cached = await asyncio.to_thread(self._cached, key, None, expected_type, legacy_key)
        if cached is not None:
            return cached
        stale = await asyncio.to_thread(self._cached, key, 86400 * 30, expected_type, legacy_key)
        if generation != self._cache_generation:
            return await self._swr(key, fetch, refresh=refresh, imdb_id=imdb_id, title=title, expected_type=expected_type, legacy_key=legacy_key)
        task = self._refresh_tasks.get(key)
        if task is None:
            if time.monotonic() < self._retry_after.get(key, 0):
                if stale is not None and not refresh:
                    return stale
                raise ExternalServiceError("Metadata refresh is temporarily unavailable", status_code=503)
            if len(self._refresh_tasks) >= 16:
                if stale is not None:
                    return stale
                raise ExternalServiceError("Metadata refresh is busy", status_code=503)

            async def run():
                try:
                    async with asyncio.timeout(45):
                        result = await fetch()
                        await asyncio.to_thread(self._cache.set, key, result, imdb_id, title)
                        self._cache_generation += 1
                        self._retry_after.pop(key, None)
                        return result
                except Exception:
                    if len(self._retry_after) >= 256:
                        self._retry_after.pop(next(iter(self._retry_after)))
                    self._retry_after[key] = time.monotonic() + 60
                    raise
                finally:
                    self._refresh_tasks.pop(key, None)

            task = asyncio.create_task(run())
            self._refresh_tasks[key] = task
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
            task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
        if stale is not None and not refresh:
            return stale
        try:
            return await asyncio.shield(task)
        except (httpx.HTTPError, TimeoutError) as error:
            raise ExternalServiceError("Metadata refresh failed", status_code=503) from error

    async def movie_meta(self, imdb_id: str, media_type: str = "movie", language="ru", refresh=False):
        clean_id = imdb_id.strip()
        # Existing RU movie keys remain readable; type and language never share a slot.
        key = self._meta_key(clean_id, media_type, language)
        return await self._swr(key, lambda: self._fetch_movie_meta(clean_id, media_type, language),
                               refresh=refresh, imdb_id=clean_id, expected_type=media_type,
                               legacy_key=f"meta:{clean_id}" if language == "ru" and media_type == "series" else None)

    async def _fetch_movie_meta(
        self, imdb_id: str, media_type: str = "movie", language="ru"
    ) -> dict[str, Any]:
        """Fetch details for movie/series by IMDB id.

        Flow: cache -> Cinemeta -> TVmaze (fallback) -> Wikidata RU labels -> merge -> cache -> return.
        """
        clean_id = imdb_id.strip()
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
            wiki = await self._wikidata.lookup_by_imdb(clean_id) if language == "ru" else None
            if wiki and language == "ru":
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
        return meta

    async def search_catalog(self, query: str, type_: str = "movie", language="ru", refresh=False):
        clean_q = query.strip()
        if not clean_q:
            return []
        key = f"search:{language}:{type_}:{clean_q.lower()}"
        async def fetch():
            return {"items": await self._fetch_search_catalog(clean_q, type_, language)}
        result = await self._swr(key, fetch, refresh=refresh, title=clean_q)
        return result["items"]

    async def _fetch_search_catalog(
        self, query: str, type_: str = "movie", language="ru"
    ) -> list[dict[str, Any]]:
        """Search catalog with offline cache, multi-provider fallback, and RU localization."""
        clean_q = query.strip()
        if not clean_q:
            return []

        results: list[dict[str, Any]] = []
        failed = False

        # 1. Search Cinemeta
        try:
            if hasattr(self._cinemeta, "search"):
                results = await self._cinemeta.search(clean_q, type_)
            elif hasattr(self._cinemeta, "search_metadata"):
                results = await self._cinemeta.search_metadata(clean_q, type_)
            elif hasattr(self._cinemeta, "search_catalog"):
                results = await self._cinemeta.search_catalog(clean_q)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
            failed = True
            logger.warning("Cinemeta search failed for '%s': %s", clean_q, e)

        # 2. Fallback to TVmaze if Cinemeta returned empty
        if not results:
            try:
                results = await self._tvmaze.search(clean_q)
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
                failed = True
                logger.warning("TVmaze search failed for '%s': %s", clean_q, e)

        if failed and not results:
            raise ExternalServiceError("Catalog search is unavailable", status_code=503)

        # 3. Enrich top results with Wikidata RU labels
        for r in results[:4] if language == "ru" else []:
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
        from backend.infrastructure.catalog.enrich import _active_background_tasks

        self._background_tasks.update(_active_background_tasks.values())
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
            logger.debug(
                "Metadata already fetched for %s, retrying poster download only", torrent_hash
            )

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

        if has_meta and not poster_file:
            return

        imdb_id = meta.get("id") or meta.get("imdb_id")
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
                imdb_id,
            )
        except sqlite3.Error as db_err:
            logger.error(
                "Failed to save metadata to DB for %s: %s",
                torrent_hash,
                db_err,
            )
