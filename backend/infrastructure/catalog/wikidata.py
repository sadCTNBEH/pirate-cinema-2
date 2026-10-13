import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
WIKIDATA_UA = "PirateCinema/2.0 (https://github.com/sadCTNBEH/pirate-cinema-2; contact@piratecinema.local)"


def _describe_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        detail = response.text[:300].replace("\n", " ").strip()
        msg = f"HTTP {response.status_code}"
        if detail:
            msg = f"{msg}: {detail}"
        return msg

    msg = str(exc).strip()
    if msg:
        return f"{exc.__class__.__name__}: {msg}"
    return exc.__class__.__name__


class WikidataProvider:
    """Metadata provider querying Wikidata for localized Russian labels and descriptions."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        timeout: float = 8.0,
    ):
        self._client = client
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "wikidata"

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None and not self._client.is_closed:
            return self._client
        return httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            headers={"User-Agent": WIKIDATA_UA, "Accept": "application/json"},
        )

    async def lookup_by_imdb(self, imdb_id: str) -> dict[str, Any] | None:
        """Find Wikidata entity for an IMDB ID (P345) and extract Russian title and overview."""
        clean_id = imdb_id.strip()
        if not (clean_id.startswith("tt") and clean_id[2:].isdigit()):
            return None

        client_owner = self._client is None
        client = await self._get_client()

        try:
            # 1. Search for entity with claim P345 = imdb_id
            search_params = {
                "action": "query",
                "list": "search",
                "srsearch": f"haswbstatement:P345={clean_id}",
                "format": "json",
            }
            r = await client.get(WIKIDATA_API, params=search_params)
            r.raise_for_status()
            data = r.json()
            search_results = data.get("query", {}).get("search", [])
            if not search_results:
                return None

            entity_id = search_results[0].get("title")  # e.g. "Q1079"
            if not entity_id:
                return None

            # 2. Get Russian and English labels/descriptions
            entity_params = {
                "action": "wbgetentities",
                "ids": entity_id,
                "props": "labels|descriptions",
                "languages": "ru|en",
                "format": "json",
            }
            r_ent = await client.get(WIKIDATA_API, params=entity_params)
            r_ent.raise_for_status()
            ent_data = r_ent.json()

            entity = ent_data.get("entities", {}).get(entity_id, {})
            labels = entity.get("labels", {})
            descriptions = entity.get("descriptions", {})

            title_ru = labels.get("ru", {}).get("value")
            overview_ru = descriptions.get("ru", {}).get("value")
            title_en = labels.get("en", {}).get("value")
            overview_en = descriptions.get("en", {}).get("value")

            if not title_ru and not overview_ru:
                return None

            return {
                "id": clean_id,
                "wikidata_id": entity_id,
                "title_ru": title_ru,
                "overview_ru": overview_ru,
                "title_en": title_en,
                "overview_en": overview_en,
                "source": self.name,
            }

        except httpx.HTTPError as e:
            logger.warning("Wikidata lookup error for %s: %s", clean_id, e)
            return None
        except Exception:
            logger.exception("Unexpected error querying Wikidata for %s", clean_id)
            return None
        finally:
            if client_owner and not client.is_closed:
                await client.aclose()

    async def search_by_title(self, title: str) -> dict[str, Any] | None:
        """Search Wikidata entities by title and retrieve Russian label/overview."""
        clean_title = title.strip()
        if not clean_title:
            return None

        client_owner = self._client is None
        client = await self._get_client()

        try:
            params = {
                "action": "wbsearchentities",
                "search": clean_title,
                "language": "ru",
                "format": "json",
                "limit": 3,
            }
            r = await client.get(WIKIDATA_API, params=params)
            r.raise_for_status()
            data = r.json()
            search_items = data.get("search", [])
            if not search_items:
                return None

            first = search_items[0]
            return {
                "wikidata_id": first.get("id"),
                "title_ru": first.get("label"),
                "overview_ru": first.get("description"),
                "source": self.name,
            }

        except httpx.HTTPError as e:
            logger.warning("Wikidata search error for '%s': %s", clean_title, e)
            return None
        except Exception:
            logger.exception(
                "Unexpected error searching Wikidata for '%s'", clean_title
            )
            return None
        finally:
            if client_owner and not client.is_closed:
                await client.aclose()

    async def lookup_batch_imdb(
        self, imdb_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Batch lookup Wikidata entities for multiple IMDB IDs.

        Attempts a SPARQL batch query first. Falls back to concurrent lookup_by_imdb
        if SPARQL fails or returns partial data.
        """
        valid_ids = list(
            dict.fromkeys(
                i.strip()
                for i in imdb_ids
                if i and i.strip().startswith("tt") and i.strip()[2:].isdigit()
            )
        )
        if not valid_ids:
            return {}

        results: dict[str, dict[str, Any]] = {}

        # 1. Try SPARQL query
        values_str = " ".join(f'"{i}"' for i in valid_ids)
        query = (
            "SELECT ?id ?label ?description ?image WHERE {\n"
            f"  VALUES ?id {{ {values_str} }}\n"
            "  ?item wdt:P345 ?id .\n"
            '  OPTIONAL { ?item rdfs:label ?label . FILTER(LANG(?label) = "ru") }\n'
            '  OPTIONAL { ?item schema:description ?description . FILTER(LANG(?description) = "ru") }\n'
            "  OPTIONAL { ?item wdt:P18 ?image }\n"
            "}"
        )

        client_owner = self._client is None
        client = await self._get_client()

        sparql_success = False
        try:
            headers = {
                "User-Agent": WIKIDATA_UA,
                "Accept": "application/sparql-results+json",
            }
            r = await client.post(
                WIKIDATA_SPARQL,
                data={"query": query, "format": "json"},
                headers=headers,
                timeout=self._timeout,
            )
            r.raise_for_status()
            data = r.json()
            bindings = data.get("results", {}).get("bindings", [])
            for b in bindings:
                cid = b.get("id", {}).get("value")
                if not cid:
                    continue
                if cid not in results:
                    results[cid] = {
                        "id": cid,
                        "title_ru": None,
                        "overview_ru": None,
                        "image_url": None,
                        "source": self.name,
                    }
                if "label" in b and not results[cid]["title_ru"]:
                    val = b["label"].get("value")
                    if val:
                        results[cid]["title_ru"] = val.strip()
                if "description" in b and not results[cid]["overview_ru"]:
                    val = b["description"].get("value")
                    if val:
                        results[cid]["overview_ru"] = val.strip()
                if "image" in b and not results[cid]["image_url"]:
                    val = b["image"].get("value")
                    if val:
                        if val.startswith("http://"):
                            val = "https://" + val[7:]
                        results[cid]["image_url"] = val
            sparql_success = True
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "Wikidata SPARQL batch failed: %s; falling back to parallel lookup",
                _describe_error(e),
            )
        finally:
            if client_owner and not client.is_closed:
                await client.aclose()

        fallback_ids = valid_ids
        if sparql_success:
            fallback_ids = [i for i in valid_ids if i not in results]
            if not fallback_ids:
                return results
            logger.debug(
                "Wikidata SPARQL returned partial data (%d/%d); looking up missing IDs",
                len(results),
                len(valid_ids),
            )

        if not fallback_ids:
            return results

        # 2. Fallback: asyncio.gather with Semaphore(6) over lookup_by_imdb
        sem = asyncio.Semaphore(6)

        async def _single_lookup(i_id: str):
            async with sem:
                try:
                    res = await self.lookup_by_imdb(i_id)
                    if res:
                        results[i_id] = {
                            "id": i_id,
                            "title_ru": res.get("title_ru"),
                            "overview_ru": res.get("overview_ru"),
                            "image_url": None,
                            "source": self.name,
                        }
                except Exception as ex:  # noqa: BLE001
                    logger.debug("Fallback lookup failed for %s: %s", i_id, ex)

        await asyncio.gather(
            *[_single_lookup(i) for i in fallback_ids], return_exceptions=True
        )
        return results
