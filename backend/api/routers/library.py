import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from backend.api import deps
from backend.api.schemas.common import StatusResponse
from backend.api.schemas.library import (
    LibraryFilter,
    LibraryItemResponse,
    NextUnwatchedResponse,
)
from backend.exceptions import AppException
from backend.services.library import LibraryService
from backend.services.metadata import MetadataService

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
    type: str | None = None,
    status: str | None = None,
    year: int | None = None,
    genre: str | None = None,
    sort: str | None = None,
    service: Annotated[LibraryService, Depends(deps.get_library_service)] = None,
) -> list[dict[str, Any]]:
    try:
        filter_params = LibraryFilter(
            type=type,
            status=status,
            year=year,
            genre=genre,
            sort=sort,
        )
        return await service.get_filtered_library(filter_params)
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@library_router.get("/{hash}/progress")
@library_direct_router.get("/{hash}/progress", include_in_schema=False)
async def get_progress(
    hash: str,
    service: Annotated[LibraryService, Depends(deps.get_library_service)],
) -> dict[str, Any]:
    try:
        return await service.get_season_progress(hash)
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@library_router.get("/{hash}/next-unwatched", response_model=NextUnwatchedResponse)
@library_direct_router.get(
    "/{hash}/next-unwatched",
    response_model=NextUnwatchedResponse,
    include_in_schema=False,
)
async def get_next_unwatched(
    hash: str,
    service: Annotated[LibraryService, Depends(deps.get_library_service)],
) -> dict[str, Any]:
    try:
        return await service.get_next_unwatched(hash)
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
    service: Annotated[MetadataService, Depends(deps.get_metadata_service)],
) -> list[dict[str, Any]]:
    try:
        return await service.popular_movies()
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@library_router.get("/popular/series")
@library_direct_router.get("/popular/series", include_in_schema=False)
async def popular_series(
    service: Annotated[MetadataService, Depends(deps.get_metadata_service)],
) -> list[dict[str, Any]]:
    try:
        return await service.popular_series()
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@library_router.get("/meta/{imdb_id}")
async def movie_meta(
    imdb_id: str,
    type: str = "movie",
    service: Annotated[MetadataService, Depends(deps.get_metadata_service)] = None,
) -> dict[str, Any]:
    try:
        return await service.movie_meta(imdb_id, type)
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@library_router.get("/meta/search")
async def movie_meta_search(
    q: str,
    type: str = "movie",
    service: Annotated[MetadataService, Depends(deps.get_metadata_service)] = None,
) -> list[dict[str, Any]]:
    try:
        return await service.search_movie_meta(q, type)
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
    service: Annotated[LibraryService, Depends(deps.get_library_service)] = None,
) -> dict[str, Any]:
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
