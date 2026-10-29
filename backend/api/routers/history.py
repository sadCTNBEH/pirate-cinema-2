from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api import deps
from backend.api.schemas.common import StatusResponse
from backend.api.schemas.history import (
    AnimePlaybackRequest,
    FileHistoryEntry,
    HistoryItemResponse,
    MarkWatchedRequest,
)
from backend.exceptions import AppException
from backend.services.history import HistoryService

history_router = APIRouter(prefix="/api/history", tags=["history"])


@history_router.get("", response_model=list[HistoryItemResponse])
async def get_history(
    limit: int = Query(default=200, ge=1, le=500),
    service: Annotated[HistoryService, Depends(deps.get_history_service)] = None,
) -> list[dict[str, Any]]:
    try:
        return await service.get_history(limit)
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@history_router.get("/continue", response_model=list[FileHistoryEntry])
async def get_continue_watching(
    limit: int = Query(default=20, ge=1, le=100),
    service: Annotated[HistoryService, Depends(deps.get_history_service)] = None,
) -> list[dict[str, Any]]:
    try:
        return await service.get_continue_watching(limit)
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@history_router.get('/anime/{media_id}')
async def anime_resume(media_id: str, service: Annotated[HistoryService, Depends(deps.get_history_service)]):
    try:
        return await service.anime_resume(media_id)
    except AppException as error:
        raise HTTPException(error.status_code, error.message) from error


@history_router.post('/anime', response_model=HistoryItemResponse)
async def save_anime_playback(
    request: AnimePlaybackRequest,
    service: Annotated[HistoryService, Depends(deps.get_history_service)],
    metadata: Annotated[Any, Depends(deps.get_metadata_service)] = None,
    online: Annotated[Any, Depends(deps.get_online_service)] = None,
):
    from backend.services.anime_identity import playback_identity
    try:
        context = await playback_identity(request.model_dump(), metadata, online)
        return await service.save_anime_playback(context)
    except AppException as error:
        raise HTTPException(error.status_code, error.message) from error


@history_router.post('/anime/complete', response_model=StatusResponse)
async def complete_anime_playback(
    request: AnimePlaybackRequest,
    service: Annotated[HistoryService, Depends(deps.get_history_service)],
    metadata: Annotated[Any, Depends(deps.get_metadata_service)] = None,
    online: Annotated[Any, Depends(deps.get_online_service)] = None,
):
    from backend.services.anime_identity import playback_identity
    try:
        context = await playback_identity(request.model_dump(), metadata, online)
        # Completion must not replace the latest resume row after auto-next.
        await service.mark_watched_episode(imdb_id=context['media_id'],
            season=context['season'], episode=context['episode'], watched=True)
        return {'status': 'ok'}
    except AppException as error:
        raise HTTPException(error.status_code, error.message) from error


@history_router.post("/mark-watched", response_model=StatusResponse)
async def mark_watched_post(
    request: MarkWatchedRequest,
    service: Annotated[HistoryService, Depends(deps.get_history_service)] = None,
) -> dict[str, str]:
    try:
        await service.mark_watched_episode(
            title_id=request.title_id,
            imdb_id=request.imdb_id,
            torrent_hash=request.torrent_hash,
            file_index=request.file_index,
            season=request.season,
            episode=request.episode,
            watched=request.watched,
        )
        return {"status": "ok"}
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@history_router.get("/next-unwatched")
async def get_next_unwatched(
    imdb_id: str | None = Query(default=None),
    season: int | None = Query(default=None),
    title_id: str | None = Query(default=None),
    torrent_hash: str | None = Query(default=None),
    service: Annotated[HistoryService, Depends(deps.get_history_service)] = None,
) -> dict[str, Any]:
    try:
        result = await service.get_next_unwatched(
            imdb_id=imdb_id,
            season=season,
            title_id=title_id,
            torrent_hash=torrent_hash,
        )
        return result or {}
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@history_router.post(
    "/{torrent_hash}/{file_index}/watched", response_model=StatusResponse
)
async def mark_watched(
    torrent_hash: str,
    file_index: int,
    service: Annotated[HistoryService, Depends(deps.get_history_service)] = None,
) -> dict[str, str]:
    try:
        await service.mark_watched(torrent_hash, file_index)
        return {"status": "ok"}
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@history_router.delete("/{id}", response_model=StatusResponse)
async def delete_history_entry_by_id(
    id: str,
    service: Annotated[HistoryService, Depends(deps.get_history_service)] = None,
) -> dict[str, str]:
    try:
        await service.delete_entry_by_id(id)
        return {"status": "ok"}
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@history_router.delete("/{torrent_hash}/{file_index}", response_model=StatusResponse)
async def delete_history_entry(
    torrent_hash: str,
    file_index: int,
    service: Annotated[HistoryService, Depends(deps.get_history_service)] = None,
) -> dict[str, str]:
    try:
        await service.delete_entry(torrent_hash, file_index)
        return {"status": "ok"}
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
