"""FastAPI online videos and playlists router."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from backend.api import deps
from backend.api.schemas.online import (
    OnlineHistoryItem,
    OnlineSearchRequest,
    OnlineSearchResult,
    Playlist,
    PlaylistCreateRequest,
    PlaylistItemCreateRequest,
    PlaylistUpdateRequest,
    PlayOnlineRequest,
    PlayOnlineResponse,
)
from backend.exceptions import AppException
from backend.services.online.online_history import OnlineHistoryService
from backend.services.online.playlist_service import PlaylistService
from backend.services.online.service import OnlineService
from backend.services.playback import PlaybackService

logger = logging.getLogger(__name__)

online_router = APIRouter(prefix="/api/online", tags=["online"])


@online_router.post("/search", response_model=list[OnlineSearchResult])
async def search_online(
    request: OnlineSearchRequest,
    service: Annotated[OnlineService, Depends(deps.get_online_service)],
):
    try:
        return await service.search(request.query, provider=request.provider)
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@online_router.post("/play", response_model=PlayOnlineResponse)
async def play_online(
    request: PlayOnlineRequest,
    online_service: Annotated[OnlineService, Depends(deps.get_online_service)],
    playback_service: Annotated[PlaybackService, Depends(deps.get_playback_service)],
    online_history_service: Annotated[
        OnlineHistoryService, Depends(deps.get_online_history_service)
    ],
):
    try:
        stream_info = await online_service.resolve_stream(
            request.provider, request.id, quality=request.quality
        )

        # Check existing progress to restore playback position
        start_time = 0
        history_items = online_history_service.list_history(limit=500)
        for h in history_items:
            if h.provider == request.provider and h.item_id == request.id:
                if not h.is_watched and h.playback_timecode > 0:
                    start_time = h.playback_timecode
                break

        status = await playback_service.launch_online(
            provider=request.provider,
            video_id=request.id,
            stream_url=stream_info.url,
            title=stream_info.title,
            start_time=start_time,
            thumbnail=stream_info.thumbnail,
            duration=stream_info.duration,
            playlist_id=request.playlist_id,
            episode_index=request.episode_index,
            quality=stream_info.quality,
        )

        return PlayOnlineResponse(
            url=stream_info.url,
            title=stream_info.title,
            thumbnail=stream_info.thumbnail,
            duration=stream_info.duration,
            quality=stream_info.quality,
            timecode=start_time,
            provider=request.provider,
            id=request.id,
            available_qualities=stream_info.available_qualities,
            status=status,
        )
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ─── Playlists ───


@online_router.get("/playlists", response_model=list[Playlist])
async def list_playlists(
    playlist_service: Annotated[PlaylistService, Depends(deps.get_playlist_service)],
):
    try:
        return playlist_service.list_playlists()
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@online_router.post("/playlists", response_model=Playlist)
async def create_playlist(
    request: PlaylistCreateRequest,
    playlist_service: Annotated[PlaylistService, Depends(deps.get_playlist_service)],
):
    try:
        return playlist_service.create_playlist(request.title)
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@online_router.get("/playlists/{playlist_id}", response_model=Playlist)
async def get_playlist(
    playlist_id: Annotated[str, Path(min_length=1, max_length=100)],
    playlist_service: Annotated[PlaylistService, Depends(deps.get_playlist_service)],
):
    try:
        return playlist_service.get_playlist(playlist_id)
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@online_router.patch("/playlists/{playlist_id}", response_model=Playlist)
async def update_playlist(
    playlist_id: Annotated[str, Path(min_length=1, max_length=100)],
    request: PlaylistUpdateRequest,
    playlist_service: Annotated[PlaylistService, Depends(deps.get_playlist_service)],
):
    try:
        return playlist_service.update_playlist(playlist_id, request.title)
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@online_router.delete("/playlists/{playlist_id}")
async def delete_playlist(
    playlist_id: Annotated[str, Path(min_length=1, max_length=100)],
    playlist_service: Annotated[PlaylistService, Depends(deps.get_playlist_service)],
):
    try:
        playlist_service.delete_playlist(playlist_id)
        return {"status": "deleted"}
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@online_router.post("/playlists/{playlist_id}/items", response_model=Playlist)
async def add_playlist_item(
    playlist_id: Annotated[str, Path(min_length=1, max_length=100)],
    request: PlaylistItemCreateRequest,
    playlist_service: Annotated[PlaylistService, Depends(deps.get_playlist_service)],
):
    try:
        item = OnlineSearchResult(
            id=request.id,
            title=request.title,
            provider=request.provider,
            thumbnail=request.thumbnail,
            duration=request.duration,
            is_playlist=request.is_playlist,
        )
        return playlist_service.add_item(playlist_id, item)
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@online_router.delete(
    "/playlists/{playlist_id}/items/{item_id:path}", response_model=Playlist
)
async def remove_playlist_item(
    playlist_id: Annotated[str, Path(min_length=1, max_length=100)],
    item_id: Annotated[str, Path(min_length=1, max_length=1000)],
    playlist_service: Annotated[PlaylistService, Depends(deps.get_playlist_service)],
):
    try:
        return playlist_service.remove_item(playlist_id, item_id)
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


# ─── History ───


@online_router.get("/history", response_model=list[OnlineHistoryItem])
async def get_online_history(
    history_service: Annotated[
        OnlineHistoryService, Depends(deps.get_online_history_service)
    ],
    limit: int = 100,
):
    try:
        return history_service.list_history(limit=limit)
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@online_router.delete("/history/{provider}/{item_id:path}")
async def delete_history_item(
    provider: Annotated[str, Path(min_length=1, max_length=50)],
    item_id: Annotated[str, Path(min_length=1, max_length=1000)],
    history_service: Annotated[
        OnlineHistoryService, Depends(deps.get_online_history_service)
    ],
):
    try:
        history_service.delete_history_item(provider, item_id)
        return {"status": "deleted"}
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@online_router.delete("/history")
async def clear_online_history(
    history_service: Annotated[
        OnlineHistoryService, Depends(deps.get_online_history_service)
    ],
):
    try:
        history_service.clear_history()
        return {"status": "cleared"}
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
