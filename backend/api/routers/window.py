"""Window controls API router (frameless desktop chrome)."""

from fastapi import APIRouter

from backend.gui import window_api

window_router = APIRouter(prefix="/api/window", tags=["window"])


@window_router.post("/minimize")
async def api_minimize():
    return {"success": window_api.minimize()}


@window_router.post("/maximize")
async def api_maximize():
    return {"success": window_api.maximize(), "is_maximized": True}


@window_router.post("/restore")
async def api_restore():
    return {"success": window_api.restore(), "is_maximized": False}


@window_router.post("/toggle_maximize")
async def api_toggle_maximize():
    is_max = window_api.toggle_maximize()
    return {"is_maximized": is_max}


@window_router.get("/state")
async def api_get_state():
    return {"is_maximized": window_api.is_maximized()}


@window_router.post("/close")
async def api_close():
    return {"success": window_api.close()}
