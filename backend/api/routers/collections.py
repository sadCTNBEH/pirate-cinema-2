from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from backend.api import deps
from backend.api.schemas.collections import (
    CollectionItemRequest,
    CollectionItemResponse,
    CollectionMembershipResponse,
    CollectionName,
)
from backend.api.schemas.common import StatusResponse
from backend.exceptions import AppException
from backend.services.collections import CollectionService

collections_router = APIRouter(prefix="/api/collections", tags=["collections"])


@collections_router.get(
    "/membership/{media_id}", response_model=CollectionMembershipResponse
)
async def get_collection_membership(
    media_id: str,
    service: Annotated[CollectionService, Depends(deps.get_collection_service)],
) -> dict[str, bool]:
    try:
        memberships = await service.get_memberships(media_id)
        return {
            "favorites": "favorites" in memberships,
            "watch_later": "watch_later" in memberships,
        }
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@collections_router.get("/{list_name}", response_model=list[CollectionItemResponse])
async def get_collection(
    list_name: CollectionName,
    service: Annotated[CollectionService, Depends(deps.get_collection_service)],
) -> list[dict]:
    try:
        return await service.get_items(list_name)
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@collections_router.put("/{list_name}/{media_id}", response_model=StatusResponse)
async def add_to_collection(
    list_name: CollectionName,
    media_id: str,
    item: CollectionItemRequest,
    service: Annotated[CollectionService, Depends(deps.get_collection_service)],
) -> dict[str, str]:
    if item.media_id != media_id:
        raise HTTPException(status_code=422, detail="media_id must match request path")
    try:
        await service.add_item(list_name, item.model_dump())
        return {"status": "ok"}
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@collections_router.delete("/{list_name}/{media_id}", response_model=StatusResponse)
async def remove_from_collection(
    list_name: CollectionName,
    media_id: str,
    service: Annotated[CollectionService, Depends(deps.get_collection_service)],
) -> dict[str, str]:
    try:
        await service.remove_item(list_name, media_id)
        return {"status": "ok"}
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
