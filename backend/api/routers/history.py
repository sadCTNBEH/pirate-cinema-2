from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api import deps
from backend.api.schemas.common import StatusResponse
from backend.api.schemas.history import HistoryItemResponse
from backend.exceptions import AppException
from backend.services.history import HistoryService

history_router = APIRouter(prefix="/api/history", tags=["history"])


@history_router.get("", response_model=list[HistoryItemResponse])
async def get_history(
    limit: int = Query(default=200, ge=1, le=500),
    service: Annotated[HistoryService, Depends(deps.get_history_service)] = None,
) -> list[dict]:
    try:
        return await service.get_history(limit)
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
