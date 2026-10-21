"""FastAPI In-App Updater router."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.api import deps
from backend.api.schemas.updater import (
    UpdateActionResponse,
    UpdateCheckResponse,
    UpdateStatusResponse,
)
from backend.exceptions import AppException
from backend.services.updater import (
    UpdateError,
    UpdateInstallationError,
    UpdaterService,
)

logger = logging.getLogger(__name__)

updater_router = APIRouter(prefix="/api/updater", tags=["updater"])


class ApplyUpdateRequest(BaseModel):
    dry_run: bool = False


@updater_router.get("/check", response_model=UpdateCheckResponse)
async def check_updates(
    service: Annotated[UpdaterService, Depends(deps.get_updater_service)],
) -> UpdateCheckResponse:
    """Check GitHub Releases for newer stable versions."""
    try:
        return await service.check_for_updates()
    except (UpdateError, AppException, OSError, ValueError) as err:
        logger.warning("Error checking for updates: %s", err)
        raise HTTPException(status_code=500, detail=str(err)) from err


@updater_router.get("/status", response_model=UpdateStatusResponse)
async def get_update_status(
    service: Annotated[UpdaterService, Depends(deps.get_updater_service)],
) -> UpdateStatusResponse:
    """Get current updater status and download progress."""
    return service.get_status()


@updater_router.post("/download", response_model=UpdateStatusResponse)
async def start_download(
    service: Annotated[UpdaterService, Depends(deps.get_updater_service)],
) -> UpdateStatusResponse:
    """Start asynchronous streaming download and SHA-256 verification of the update."""
    try:
        return await service.start_download()
    except (UpdateError, AppException, OSError, ValueError) as err:
        logger.warning("Error starting update download: %s", err)
        raise HTTPException(status_code=400, detail=str(err)) from err


@updater_router.post("/apply", response_model=UpdateActionResponse)
async def apply_update(
    service: Annotated[UpdaterService, Depends(deps.get_updater_service)],
    body: ApplyUpdateRequest | None = None,
) -> UpdateActionResponse:
    """Launch the detached external update helper and restart the application."""
    dry_run = body.dry_run if body else False
    try:
        return await service.apply_update(dry_run=dry_run)
    except (UpdateInstallationError, UpdateError, AppException, OSError, ValueError) as err:
        logger.warning("Error applying update: %s", err)
        raise HTTPException(status_code=400, detail=str(err)) from err


@updater_router.post("/cancel", response_model=UpdateStatusResponse)
async def cancel_download(
    service: Annotated[UpdaterService, Depends(deps.get_updater_service)],
) -> UpdateStatusResponse:
    """Cancel any active update download."""
    try:
        return await service.cancel_download()
    except (UpdateError, AppException, OSError, ValueError) as err:
        logger.warning("Error cancelling update download: %s", err)
        raise HTTPException(status_code=400, detail=str(err)) from err
