"""FastAPI router for Web Remote control."""

from fastapi import APIRouter

from backend.services.remote import get_remote_info

remote_router = APIRouter(prefix="/api/remote", tags=["remote"])


@remote_router.get("/info")
async def get_info():
    """Return local LAN IP, port, remote URL and QR code SVG."""
    return get_remote_info()
