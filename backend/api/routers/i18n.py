from backend.api.deps import _load_settings

"""FastAPI routers: library, player, settings, catalog."""

from fastapi import APIRouter

from backend.services.i18n_service import TRANSLATIONS

# ─── Router: Global ───

i18n_router = APIRouter(prefix="/api/i18n", tags=["i18n"])

@i18n_router.get("")
async def get_i18n_strings():
    prefs = _load_settings()
    lang = prefs.get("language", "ru")
    strings = TRANSLATIONS.get(lang, TRANSLATIONS.get("ru", {}))
    return {"lang": lang, "strings": strings}
