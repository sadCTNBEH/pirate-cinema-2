"""Window controls API router (frameless desktop chrome & embedded player)."""

from fastapi import APIRouter
from pydantic import BaseModel

from backend.gui import window_api

window_router = APIRouter(prefix="/api/window", tags=["window"])


class PlayerBoundsPayload(BaseModel):
    x: float
    y: float
    width: float
    height: float
    viewport_width: float = 0
    viewport_height: float = 0
    clip_top: float = 36
    clip_left: float = 0
    clip_right: float = 0
    clip_bottom: float = 0


class FullscreenPayload(BaseModel):
    fullscreen: bool | None = None


class InputFocusPayload(BaseModel):
    focused: bool


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
    return {
        "is_maximized": window_api.is_maximized(),
        "is_fullscreen": window_api.is_fullscreen(),
    }


@window_router.post("/close")
async def api_close():
    return {"success": window_api.close()}


@window_router.post("/player_bounds")
async def api_set_player_bounds(payload: PlayerBoundsPayload):
    ok = window_api.set_player_bounds(
        x=payload.x,
        y=payload.y,
        width=payload.width,
        height=payload.height,
        viewport_width=payload.viewport_width,
        viewport_height=payload.viewport_height,
        clip_top=payload.clip_top,
        clip_left=payload.clip_left,
        clip_right=payload.clip_right,
        clip_bottom=payload.clip_bottom,
    )
    return {"success": ok}


@window_router.post("/hide_player")
async def api_hide_player():
    return {"success": window_api.hide_player_panel()}


@window_router.post("/fullscreen")
async def api_fullscreen(payload: FullscreenPayload):
    if payload.fullscreen is None:
        is_fs = window_api.toggle_fullscreen()
    else:
        is_fs = window_api.set_fullscreen(payload.fullscreen)
    return {"is_fullscreen": is_fs}


@window_router.post("/input_focus")
async def api_set_input_focus(payload: InputFocusPayload):
    return {"focused": window_api.set_input_focused(payload.focused)}

