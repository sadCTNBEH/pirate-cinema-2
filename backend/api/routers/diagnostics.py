"""FastAPI Diagnostics & Health router."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from backend.api import deps
from backend.api.schemas.diagnostics import DiagnosticsResponse
from backend.exceptions import AppException
from backend.services.diagnostics import DiagnosticsService

logger = logging.getLogger(__name__)

diagnostics_router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


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
