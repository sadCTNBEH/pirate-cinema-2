"""FastAPI router for Web Remote control and remote playback launch."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.api import deps
from backend.models.playback import PlayCommand
from backend.services.library import LibraryService
from backend.services.magnet import MagnetService
from backend.services.playback import PlaybackService
from backend.services.remote import get_remote_info

logger = logging.getLogger(__name__)

remote_router = APIRouter(prefix="/api/remote", tags=["remote"])


class RemotePlayRequest(BaseModel):
    hash: str | None = None
    magnet: str | None = None
    title: str = ""
    file_id: int | None = None
    file_name: str | None = None
    fullscreen: bool | None = False


@remote_router.get("/info")
async def get_info():
    """Return local LAN IP, port, remote URL and QR code SVG."""
    return get_remote_info()


@remote_router.post("/play")
async def remote_play(
    request: RemotePlayRequest,
    playback_service: Annotated[PlaybackService, Depends(deps.get_playback_service)],
    magnet_service: Annotated[MagnetService, Depends(deps.get_magnet_service)],
    library_service: Annotated[LibraryService, Depends(deps.get_library_service)],
) -> dict[str, Any]:
    """Launch playback on the host PC from the smartphone remote."""
    target_hash = request.hash
    if not target_hash and request.magnet:
        try:
            add_res = await magnet_service.add_magnet(request.magnet, request.title)
            target_hash = add_res.get("hash")
        except Exception as e:
            logger.warning("Failed to add magnet in remote play: %s", e)

    if not target_hash:
        raise HTTPException(status_code=400, detail="Missing torrent hash or magnet")

    target_file_id = request.file_id
    target_file_name = request.file_name or request.title or "Video"

    # Auto-detect best video file if file_id is not specified
    if target_file_id is None:
        try:
            files_data = await library_service.get_torrent_files_structure(
                target_hash, title=request.title
            )
            candidates: list[dict[str, Any]] = []
            if files_data.get("seasons"):
                seasons = files_data["seasons"]
                sorted_keys = sorted(
                    seasons.keys(),
                    key=lambda k: int(k) if str(k).isdigit() else 999,
                )
                for k in sorted_keys:
                    if seasons[k]:
                        candidates = seasons[k]
                        break
            elif files_data.get("movies"):
                candidates = files_data["movies"]
            elif files_data.get("files"):
                candidates = files_data["files"]
            elif files_data.get("flat_files"):
                candidates = files_data["flat_files"]

            if candidates:
                # If movies / single video, choose largest file
                if files_data.get("type") == "movie" or not files_data.get("seasons"):
                    chosen = max(candidates, key=lambda f: f.get("length", 0))
                else:
                    chosen = candidates[0]
                target_file_id = chosen.get("id", 0)
                target_file_name = chosen.get("name", target_file_name)
            else:
                target_file_id = 0
        except Exception as e:
            logger.debug("Auto-detect video file error in remote play: %s", e)
            target_file_id = 0

    cmd = PlayCommand(
        hash=target_hash,
        file_id=target_file_id,
        file_name=target_file_name,
        start_time=0,
    )

    try:
        status = await playback_service.launch(cmd)
    except Exception as e:
        logger.exception("Failed to launch playback from remote: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e

    # Unhide / restore PC window if minimized to tray
    try:
        from backend.gui import window_api

        window_api.show()
    except Exception:
        pass

    if request.fullscreen:
        try:
            from backend.gui import window_api

            window_api.set_fullscreen(True)
        except Exception:
            pass

    return {
        "status": status,
        "hash": target_hash,
        "file_id": target_file_id,
        "file_name": target_file_name,
    }
