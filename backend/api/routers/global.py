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



# ─── Router: Global ───

i18n_router = APIRouter(prefix="/api/i18n", tags=["i18n"])

@i18n_router.get("")
async def get_i18n_strings():
    prefs = _load_settings()
    lang = prefs.get("language", "ru")
    strings = TRANSLATIONS.get(lang, TRANSLATIONS.get("ru", {}))
    return {"lang": lang, "strings": strings}
