"""FastAPI routers: library, player, settings, catalog."""
import asyncio
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from urllib import error

import aiofiles
import anyio
import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from backend.services.backup import create_backup_zip, restore_backup_zip
from backend.services.catalog import clean_title, search_metadata

from .. import __version__
from ..config import get_data_dir
from ..services import catalog as catalog_svc
from ..services import db, torrserver
from ..services.i18n import TRANSLATIONS, t
from ..services.mpv import MPVController

# ─── Shared state ─────────────────────────────────────────────────────────────
_mpv = MPVController()
logger = logging.getLogger(__name__)

def _load_settings():
    settings_file = get_data_dir() / "preferences.json"
    try:
        with open(settings_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}

def _save_settings(data):
    settings_dir = get_data_dir()
    
    try:
        with open(settings_dir / "preferences.json", "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        logger.exception("Failed to save preferences")

_torrserver_url = _load_settings().get("torrserver_endpoint", "http://127.0.0.1:8090")



# ─── Router: Search ───

search_router = APIRouter(prefix="/api/search", tags=["search"])

@search_router.get("")
async def search(q: str = Query(..., min_length=1)):
    try:
        return await torrserver.search_all(_torrserver_url, q)
    except httpx.HTTPError as e:
        logger.exception("TorrServer search failed for query")
        raise HTTPException(status_code=502, detail=f"TorrServer search error: {e}") from e


