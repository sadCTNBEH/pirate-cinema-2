"""FastAPI player router."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from backend.api import deps
from backend.api.deps import get_playback_service
from backend.api.schemas.player import (
    MagnetRequest,
    MagnetResponse,
    NextRequest,
    PlayRequest,
    PlayerStatusResponse,
)
from backend.exceptions import AppException
from backend.services.i18n import t
from backend.services.magnet import MagnetService
from backend.services.playback import PlaybackService

logger = logging.getLogger(__name__)

player_router = APIRouter(prefix="/api/player", tags=["player"])


@player_router.post("/play", response_model=PlayerStatusResponse)
async def play(
    request: PlayRequest,
    service: Annotated[PlaybackService, Depends(get_playback_service)],
):
    try:
        status = await service.launch(request)
        return {"status": status}
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@player_router.post("/next", response_model=PlayerStatusResponse)
async def play_next_endpoint(
    request: NextRequest,
    service: Annotated[PlaybackService, Depends(get_playback_service)],
):
    try:
        success = await service.play_next_file(request.hash, request.file_id)
        if success:
            return {"status": "launched"}
        raise HTTPException(status_code=404, detail=t("err_next_ep_not_found"))
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@player_router.post("/stop", response_model=PlayerStatusResponse)
async def stop_player(
    service: Annotated[PlaybackService, Depends(get_playback_service)],
):
    service.stop()
    return {"status": "stopped"}


@player_router.get("/state/{hash}/{file_id}")
async def get_state(
    hash: Annotated[str, Path(min_length=1, max_length=128)],
    file_id: Annotated[int, Path(ge=0)],
    service: Annotated[PlaybackService, Depends(get_playback_service)],
):
    try:
        return await service.get_state(hash, file_id)
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@player_router.post("/add_magnet")
async def add_magnet_endpoint(
    request: MagnetRequest,
    magnet_service: Annotated[MagnetService, Depends(deps.get_magnet_service)],
):
    try:
        return await magnet_service.add_magnet(request.magnet, request.title)
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@player_router.delete("/torrent/{hash}", response_model=PlayerStatusResponse)
async def delete_torrent(
    hash: str,
    magnet_service: Annotated[MagnetService, Depends(deps.get_magnet_service)],
):
    try:
        return await magnet_service.delete_torrent(hash)
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
