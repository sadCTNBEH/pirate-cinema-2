import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse

from backend.api import deps
from backend.api.schemas.common import StatusResponse
from backend.api.schemas.library import (
    LibraryFilter,
    LibraryItemResponse,
)
from backend.exceptions import AppException, NotFoundError
from backend.services.library import LibraryService
from backend.services.magnet import MagnetService
from backend.services.metadata import MetadataService
from backend.services.progress import SeasonProgressService

logger = logging.getLogger(__name__)

library_router = APIRouter(prefix="/api/library", tags=["library"])
library_direct_router = APIRouter(prefix="/library", tags=["library"])


@library_router.get("", response_model=list[LibraryItemResponse])
@library_router.get(
    "/", response_model=list[LibraryItemResponse], include_in_schema=False
)
@library_direct_router.get(
    "", response_model=list[LibraryItemResponse], include_in_schema=False
)
@library_direct_router.get(
    "/", response_model=list[LibraryItemResponse], include_in_schema=False
)
async def get_library(
    response: Response,
    type: str | None = None,
    status: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    year: int | None = None,
    genre: str | None = None,
    sort: str | None = None,
    order: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    service: Annotated[LibraryService, Depends(deps.get_library_service)] = None,
) -> list[dict[str, Any]]:
    try:
        filter_params = LibraryFilter(
            type=type,
            status=status,
            year=year,
            year_from=year_from,
            year_to=year_to,
            genre=genre,
            sort=sort,
            order=order,
            limit=limit,
            offset=offset,
        )
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve)) from ve

    try:
        items, total_count = await service.get_filtered_library_with_count(filter_params)
        response.headers["X-Total-Count"] = str(total_count)
        return items
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@library_router.get("/{hash}/progress")
@library_direct_router.get("/{hash}/progress", include_in_schema=False)
async def get_progress(
    hash: str,
    progress_service: Annotated[SeasonProgressService, Depends(deps.get_progress_service)],
) -> dict[str, Any]:
    try:
        return await progress_service.get_season_progress(hash)
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@library_router.get("/{hash}/next-unwatched")
@library_direct_router.get(
    "/{hash}/next-unwatched",
    include_in_schema=False,
)
async def get_next_unwatched(
    hash: str,
    progress_service: Annotated[SeasonProgressService, Depends(deps.get_progress_service)],
) -> dict[str, Any]:
    try:
        res = await progress_service.get_next_unwatched(hash)
        if not res:
            raise NotFoundError("Все серии уже просмотрены")
        return res
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@library_router.get("/recent")
async def recent(
    service: Annotated[LibraryService, Depends(deps.get_library_service)],
) -> list[dict[str, Any]]:
    try:
        return await service.get_recent_media()
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@library_router.get("/popular")
@library_direct_router.get("/popular", include_in_schema=False)
async def popular_movies(
    response: Response,
    lang: Literal["ru", "en"] = "ru",
    refresh: bool = False,
    service: Annotated[MetadataService, Depends(deps.get_metadata_service)] = None,
) -> list[dict[str, Any]]:
    try:
        data = await service.popular_movies(lang, refresh)
        fresh = await service.cache_is_fresh("movies", lang, data=data)
        response.headers["X-Catalog-Stale"] = "0" if fresh else "1"
        response.headers["X-Catalog-Age"] = str(await service.cache_age("movies", lang))
        response.headers["Cache-Control"] = "no-store"
        return data
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@library_router.get("/popular/series")
@library_direct_router.get("/popular/series", include_in_schema=False)
async def popular_series(
    response: Response,
    lang: Literal["ru", "en"] = "ru",
    refresh: bool = False,
    service: Annotated[MetadataService, Depends(deps.get_metadata_service)] = None,
) -> list[dict[str, Any]]:
    try:
        data = await service.popular_series(lang, refresh)
        fresh = await service.cache_is_fresh("series", lang, data=data)
        response.headers["X-Catalog-Stale"] = "0" if fresh else "1"
        response.headers["X-Catalog-Age"] = str(await service.cache_age("series", lang))
        response.headers["Cache-Control"] = "no-store"
        return data
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@library_router.get("/popular/anime")
async def popular_anime(
    category: Literal["popular", "season", "rated"] = "popular",
    service: Annotated[MetadataService, Depends(deps.get_metadata_service)] = None,
):
    try:
        return await service.anime_catalog(category)
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@library_router.get("/meta/unified")
async def unified_search(
    q: str,
    lang: Literal["ru", "en"] = "ru",
    service: Annotated[MetadataService, Depends(deps.get_metadata_service)] = None,
):
    try:
        return await service.unified_catalog(q, lang)
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@library_router.get("/meta/search")
async def movie_meta_search(
    q: str,
    type: str = "movie",
    lang: Literal["ru", "en"] = "ru",
    refresh: bool = False,
    service: Annotated[MetadataService, Depends(deps.get_metadata_service)] = None,
) -> list[dict[str, Any]]:
    try:
        return await service.search_movie_meta(q, type, lang, refresh)
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@library_router.get("/anime/yummy/for-shikimori/{anime_id}")
async def yummy_for_shikimori(
    anime_id: int,
    service: Annotated[MetadataService, Depends(deps.get_metadata_service)] = None,
):
    try:
        return await service._swr(f'yummy:shikimori:{anime_id}', lambda: service._yummy.for_shikimori(anime_id))
    except AppException as e:
        raise HTTPException(e.status_code, e.message) from e


@library_router.get("/anime/yummy/{anime_id}/parts")
async def yummy_parts(
    anime_id: int,
    service: Annotated[MetadataService, Depends(deps.get_metadata_service)],
):
    try:
        async def fetch():
            return {'items': await service._yummy.parts(str(anime_id))}
        return (await service._swr(f'yummy:parts:{anime_id}', fetch))['items']
    except AppException as error:
        raise HTTPException(error.status_code, error.message) from error


@library_router.get("/anime/yummy/{anime_id}/players")
async def yummy_players(
    anime_id: int,
    response: Response,
    service: Annotated[MetadataService, Depends(deps.get_metadata_service)] = None,
):
    response.headers["Cache-Control"] = "no-store"
    try:
        return await service.yummy_players(str(anime_id))
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@library_router.get("/meta/{imdb_id}")
async def movie_meta(
    response: Response,
    imdb_id: str,
    type: str = "movie",
    lang: Literal["ru", "en"] = "ru",
    refresh: bool = False,
    service: Annotated[MetadataService, Depends(deps.get_metadata_service)] = None,
) -> dict[str, Any]:
    try:
        data = await service.movie_meta(imdb_id, type, lang, refresh)
        fresh = await service.cache_is_fresh("meta", lang, imdb_id, type)
        response.headers["X-Catalog-Stale"] = "0" if fresh else "1"
        response.headers["X-Catalog-Age"] = str(await service.cache_age("meta", lang, imdb_id, type))
        response.headers["Cache-Control"] = "no-store"
        return data
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@library_router.get("/torrents")
async def list_torrents(
    service: Annotated[LibraryService, Depends(deps.get_library_service)],
) -> dict[str, Any] | None:
    try:
        return await service.get_torrents_list()
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@library_router.get("/torrents/{hash}/files")
async def torrent_files(
    hash: str,
    title: str | None = None,
    magnet: str | None = None,
    service: Annotated[LibraryService, Depends(deps.get_library_service)] = None,
    magnet_service: Annotated[MagnetService, Depends(deps.get_magnet_service)] = None,
) -> dict[str, Any]:
    link = magnet or hash
    if link and magnet_service and not str(hash).startswith("online:"):
        try:
            await magnet_service.add_magnet(link, title or "")
        except AppException as e:
            logger.debug("Auto-add link in files endpoint: %s", e)
    try:
        return await service.get_torrent_files_structure(hash, title=title)
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@library_router.get("/poster/{hash}")
async def get_poster(
    hash: str,
    service: Annotated[LibraryService, Depends(deps.get_library_service)],
):
    try:
        poster_path = service.resolve_poster_path(hash)
        return FileResponse(poster_path)
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@library_router.delete("/history/{hash}", response_model=StatusResponse)
async def delete_history(
    hash: str,
    service: Annotated[LibraryService, Depends(deps.get_library_service)],
):
    try:
        await service.clear_history(hash)
        return {"status": "ok"}
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@library_router.delete("/torrents/{hash}", response_model=StatusResponse)
@library_router.delete("/torrent/{hash}", response_model=StatusResponse, include_in_schema=False)
@library_direct_router.delete("/torrents/{hash}", response_model=StatusResponse, include_in_schema=False)
@library_direct_router.delete("/torrent/{hash}", response_model=StatusResponse, include_in_schema=False)
async def delete_torrent_endpoint(
    hash: str,
    service: Annotated[LibraryService, Depends(deps.get_library_service)],
):
    try:
        await service.delete_torrent(hash)
        return {"status": "ok"}
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@library_router.delete("/torrents", response_model=StatusResponse)
@library_direct_router.delete("/torrents", response_model=StatusResponse, include_in_schema=False)
async def delete_all_torrents_endpoint(
    service: Annotated[LibraryService, Depends(deps.get_library_service)],
):
    try:
        await service.delete_all_torrents()
        return {"status": "ok"}
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
