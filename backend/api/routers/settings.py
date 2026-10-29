"""FastAPI settings router."""

import logging
import os
import tempfile
from pathlib import Path
from typing import Annotated

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from backend.api import deps
from backend.api.schemas.common import StatusResponse
from backend.api.schemas.settings import (
    DiagnosticsResponse,
    ServerStatusResponse,
    SettingsResponse,
    SettingsUpdate,
    UpdatesResponse,
)
from backend.exceptions import AppException
from backend.services.settings import SettingsService

logger = logging.getLogger(__name__)

settings_router = APIRouter(prefix="/api/settings", tags=["settings"])


@settings_router.get("/health")
async def health(request: Request):
    return {"error": getattr(request.app.state, "startup_error", None)}


@settings_router.get("", response_model=SettingsResponse)
async def get_settings(
    service: Annotated[SettingsService, Depends(deps.get_settings_service)],
):
    try:
        return service.get_settings()
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@settings_router.post("")
async def update_settings(
    body: SettingsUpdate,
    service: Annotated[SettingsService, Depends(deps.get_settings_service)],
):
    try:
        result = service.update_settings(body.model_dump(exclude_unset=True))
        if body.auto_next is not None:
            deps.get_playback_service().set_auto_next(body.auto_next)
        if body.auto_skip_intro is not None:
            deps.get_playback_service().set_auto_skip_intro(body.auto_skip_intro)
        return result
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@settings_router.get("/status", response_model=ServerStatusResponse)
async def server_status(
    service: Annotated[SettingsService, Depends(deps.get_settings_service)],
):
    try:
        return await service.get_server_status()
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@settings_router.get("/updates", response_model=UpdatesResponse)
async def check_updates(
    service: Annotated[SettingsService, Depends(deps.get_settings_service)],
):
    try:
        return await service.check_updates()
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@settings_router.get("/backup")
async def backup_data(
    service: Annotated[SettingsService, Depends(deps.get_settings_service)],
):
    try:
        tmp_path = service.create_backup_zip()
        return FileResponse(
            tmp_path,
            filename="pirate_cinema_backup.zip",
            background=BackgroundTask(lambda: os.remove(tmp_path)),
        )
    except Exception as e:
        logger.exception("Failed to create backup")
        raise HTTPException(status_code=500, detail=str(e)) from e


@settings_router.post("/restore", response_model=StatusResponse)
async def restore_data(
    request: Request,
    service: Annotated[SettingsService, Depends(deps.get_settings_service)],
):
    fd, tmp_path_str = tempfile.mkstemp(suffix=".zip")
    os.close(fd)

    tmp_path = Path(tmp_path_str)

    try:
        content = await request.body()
        async with aiofiles.open(tmp_path, "wb") as f:
            await f.write(content)

        service.restore_backup_zip(tmp_path)
        return {"status": "ok"}

    except (ValueError, OSError) as e:
        logger.exception("Failed to restore backup")
        raise HTTPException(status_code=500, detail=str(e)) from e

    finally:
        tmp_path.unlink(missing_ok=True)


@settings_router.post("/open_folder")
async def open_data_folder(
    service: Annotated[SettingsService, Depends(deps.get_settings_service)],
):
    try:
        return await service.open_data_folder()
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@settings_router.get("/diagnostics", response_model=DiagnosticsResponse)
async def diagnostics(
    service: Annotated[SettingsService, Depends(deps.get_settings_service)],
):
    try:
        return await service.get_diagnostics()
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
