"""FastAPI player router."""

import logging
from typing import Annotated, Any

import anyio
from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel

from backend.api import deps
from backend.api.deps import get_playback_service
from backend.api.schemas.player import (
    MagnetRequest,
    NextRequest,
    PlayerStatusResponse,
    PlayRequest,
)
from backend.exceptions import AppException
from backend.services.i18n import t
from backend.services.magnet import MagnetService
from backend.services.playback import PlaybackService

logger = logging.getLogger(__name__)

player_router = APIRouter(prefix="/api/player", tags=["player"])


class PlayerFullscreenPayload(BaseModel):
    fullscreen: bool | None = None


class FileSelectionRequest(BaseModel):
    hash: str
    season: int | None = None
    episode: int | None = None
    absolute: int | None = None
    release_title: str = ''
    file_id: int | None = None


@player_router.post('/select-file')
async def select_file(request: FileSelectionRequest,
                      service: Annotated[PlaybackService, Depends(get_playback_service)]):
    try:
        return await service.select_torrent_file(**request.model_dump())
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@player_router.post("/play", response_model=PlayerStatusResponse)
async def play(
    request: PlayRequest,
    service: Annotated[PlaybackService, Depends(get_playback_service)],
):
    try:
        status = await service.launch(request.to_command())
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
    await service.tv.finish()
    await anyio.to_thread.run_sync(service.stop)
    return {"status": "stopped"}


@player_router.post("/recover", response_model=PlayerStatusResponse)
async def recover_player(service: Annotated[PlaybackService, Depends(get_playback_service)]):
    try:
        return {"status": await service.recover()}
    except AppException as error:
        raise HTTPException(status_code=error.status_code, detail=error.message) from error


@player_router.get("/active")
async def get_active_playback(
    service: Annotated[PlaybackService, Depends(get_playback_service)],
):
    return service.get_active_playback()


@player_router.post("/fullscreen")
async def toggle_player_fullscreen(
    service: Annotated[PlaybackService, Depends(get_playback_service)],
    payload: PlayerFullscreenPayload | None = None,
    fullscreen: bool | None = None,
):
    target = payload.fullscreen if (payload and payload.fullscreen is not None) else fullscreen
    is_fs = service.set_fullscreen(target)
    return {"is_fullscreen": is_fs}


@player_router.post("/command")
async def send_player_command(
    command: list[Any],
    service: Annotated[PlaybackService, Depends(get_playback_service)],
):
    if service.tv.state:
        try:
            await service.tv.command(command)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
    else:
        await anyio.to_thread.run_sync(service.send_command, command)
    return {"success": True}


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


@player_router.get("/cast")
async def cast_info(service: Annotated[PlaybackService, Depends(get_playback_service)]):
    return service.tv.info()


@player_router.post("/cast/{action}")
async def cast_action(action: str, service: Annotated[PlaybackService, Depends(get_playback_service)]):
    try:
        if action == "discover": return await service.tv.discover()
        if action == "return": await service.tv.finish(resume=True)
        elif action == "stop": await service.tv.finish()
        else: await service.tv.start(action)
        return service.tv.info()
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
