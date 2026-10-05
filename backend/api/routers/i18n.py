"""FastAPI routers: library, player, settings, catalog."""

from fastapi import APIRouter

from backend.core.settings import load_settings
from backend.services.i18n import TRANSLATIONS

i18n_router = APIRouter(prefix="/api/i18n", tags=["i18n"])


@i18n_router.get("")
async def get_i18n_strings():
    prefs = load_settings()
    lang = prefs.get("language", "ru")
    strings = TRANSLATIONS.get(lang, TRANSLATIONS.get("ru", {}))
    return {"lang": lang, "strings": strings}
