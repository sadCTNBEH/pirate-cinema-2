"""FastAPI online videos and playlists router."""

import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from pydantic import BaseModel, Field

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
from backend.services.metadata import MetadataService
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


@online_router.get("/animego/catalog")
async def animego_catalog(
    media_id: str,
    online: Annotated[OnlineService, Depends(deps.get_online_service)],
    metadata: Annotated[MetadataService, Depends(deps.get_metadata_service)],
):
    try:
        if not media_id.startswith(('shikimori:', 'yummy:')):
            raise HTTPException(422, 'Нужна карточка аниме')
        return await online.get_provider('animego').catalog(await metadata.movie_meta(media_id))
    except TimeoutError:
        raise HTTPException(503, 'AnimeGo не ответил вовремя') from None
    except AppException as error:
        raise HTTPException(error.status_code, error.message) from error


@online_router.get("/animego/card")
async def animego_card(url: str, online: Annotated[OnlineService, Depends(deps.get_online_service)]):
    try:
        return await online.get_provider('animego').catalog_card(url)
    except AppException as error:
        raise HTTPException(error.status_code, error.message) from error


class AnimegoEmbedRequest(BaseModel):
    anime_id: int = Field(gt=0)
    episode: int = Field(ge=1, le=5000)
    translation_id: str = Field(max_length=100)
    player: str = Field(max_length=50)


@online_router.post("/animego/embed")
async def animego_embed(request: AnimegoEmbedRequest, online: Annotated[OnlineService, Depends(deps.get_online_service)]):
    try:
        return await online.get_provider('animego').embed(request.anime_id, request.episode, request.translation_id, request.player)
    except AppException as error:
        raise HTTPException(error.status_code, error.message) from error


@online_router.get("/animego/web/{token}")
async def animego_web(token: str, online: Annotated[OnlineService, Depends(deps.get_online_service)]):
    from backend.services.online.animego_web import player_html
    entry = online.get_provider('animego').embeds.get(token)
    if not entry or entry[0] <= time.monotonic():
        raise HTTPException(410, 'Плеер истёк; повторите запуск серии')
    return Response(player_html(entry[1]), media_type='text/html', headers={'Cache-Control': 'no-store',
        'Referrer-Policy': 'strict-origin-when-cross-origin'})


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
