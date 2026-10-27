"""FastAPI Diagnostics & Health router."""

import logging
from typing import Annotated

import anyio
import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from backend.api import deps
from backend.api.schemas.diagnostics import DiagnosticsResponse
from backend.exceptions import AppException
from backend.infrastructure.torrserver import process as torrserver_process
from backend.services.diagnostics import DiagnosticsService

logger = logging.getLogger(__name__)

diagnostics_router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


@diagnostics_router.post('/torrserver/restart')
async def restart_torrserver(service: Annotated[DiagnosticsService, Depends(deps.get_diagnostics_service)]):
    try:
        return await service.restart_torrserver()
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@diagnostics_router.post('/torrserver/check-update')
async def check_torrserver_update(service: Annotated[DiagnosticsService, Depends(deps.get_diagnostics_service)]):
    try:
        return await service.check_torrserver_update()
    except (RuntimeError, httpx.HTTPError, ValueError) as error:
        raise HTTPException(status_code=503, detail=f'Не удалось проверить обновления TorrServer: {error}') from error


@diagnostics_router.get('/torrserver/log', response_class=PlainTextResponse)
async def torrserver_log():
    try:
        text = await anyio.to_thread.run_sync(torrserver_process.read_log)
        from backend.services.diagnostics import ErrorBuffer

        return '\n'.join(ErrorBuffer._sanitize(line) for line in text.splitlines()[-200:])
    except RuntimeError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@diagnostics_router.get("", response_model=DiagnosticsResponse)
@diagnostics_router.get(
    "/", response_model=DiagnosticsResponse, include_in_schema=False
)
async def get_diagnostics(
    service: Annotated[DiagnosticsService, Depends(deps.get_diagnostics_service)],
) -> DiagnosticsResponse:
    try:
        data = await service.get_diagnostics()
        return DiagnosticsResponse(**data)
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
