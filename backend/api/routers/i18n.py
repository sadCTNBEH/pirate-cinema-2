from backend.api.deps import _mpv, _load_settings, _save_settings
import backend.api.deps as deps
"""FastAPI routers: library, player, settings, catalog."""
import json
import logging

from fastapi import APIRouter

from backend.core.config import get_data_dir
from backend.infrastructure.mpv.controller import MPVController
from backend.services.i18n_service import TRANSLATIONS





# ─── Router: Global ───

i18n_router = APIRouter(prefix="/api/i18n", tags=["i18n"])

@i18n_router.get("")
async def get_i18n_strings():
    prefs = _load_settings()
    lang = prefs.get("language", "ru")
    strings = TRANSLATIONS.get(lang, TRANSLATIONS.get("ru", {}))
    return {"lang": lang, "strings": strings}
