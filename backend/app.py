"""FastAPI Application Setup."""

import asyncio
import json
import logging
import sys
import zipfile
from contextlib import asynccontextmanager

import anyio
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import ClientDisconnect

from backend import __version__
from backend.api.routers.collections import collections_router
from backend.api.routers.diagnostics import diagnostics_router
from backend.api.routers.history import history_router
from backend.api.routers.i18n import i18n_router
from backend.api.routers.library import library_direct_router, library_router
from backend.api.routers.online import online_router
from backend.api.routers.player import player_router
from backend.api.routers.posters import posters_direct_router, posters_router
from backend.api.routers.search import search_router
from backend.api.routers.settings import settings_router
from backend.api.routers.updater import updater_router
from backend.api.routers.window import window_router
from backend.core.settings import BASE_DIR
from backend.exceptions import AppException
from backend.infrastructure.torrserver import process as torrserver_process
from backend.repositories import db
from backend.services.diagnostics import record_diagnostic_error

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    try:
        await anyio.to_thread.run_sync(torrserver_process.connect_or_start)
        app.state.startup_error = None
    except RuntimeError as e:
        app.state.startup_error = f"Ошибка запуска TorrServer: {e}"
        logger.warning("[WARN] TorrServer failed to start: %s", e)
        record_diagnostic_error("torrserver", "StartupError", str(e))
    except OSError as e:
        app.state.startup_error = f"Системная ошибка TorrServer: {e}"
        logger.error("[ERROR] TorrServer system error: %s", e)
        record_diagnostic_error("torrserver", "SystemError", str(e))

    if sys.platform == "win32":
        try:
            from backend.core.settings import find_mpv_binary
            if find_mpv_binary() is None:
                async def _ensure_mpv_bg():
                    try:
                        from backend.infrastructure.downloader import ensure_binaries
                        await anyio.to_thread.run_sync(ensure_binaries)
                        logger.info("[STARTUP] MPV binary downloaded in background")
                    except (OSError, RuntimeError, zipfile.BadZipFile) as bg_err:
                        logger.warning("[STARTUP] Background MPV download failed: %s", bg_err)
                        record_diagnostic_error("mpv", "DownloadError", str(bg_err))

                asyncio.create_task(_ensure_mpv_bg())
        except (OSError, RuntimeError) as mpv_chk_err:
            logger.debug("Failed to schedule background MPV check: %s", mpv_chk_err)

    yield

    logger.info("[SHUTDOWN] Stopping player processes...")
    try:
        from backend.api.deps import get_playback_service

        await get_playback_service().stop_all()
    except Exception:
        logger.exception("Failed to stop playback service on shutdown")

    logger.info("[SHUTDOWN] Awaiting background metadata tasks...")
    try:
        from backend.api.deps import get_metadata_service

        await get_metadata_service().shutdown(timeout=3.0)
    except Exception:
        logger.exception("Failed to shutdown metadata service tasks")

    logger.info("[SHUTDOWN] Closing online service...")
    try:
        from backend.api.deps import get_online_service

        await get_online_service().close()
    except (RuntimeError, OSError) as e:
        logger.warning("Failed to close online service on shutdown: %s", e)

    logger.info("[SHUTDOWN] Stopping TorrServer process...")
    await anyio.to_thread.run_sync(torrserver_process.stop)


app = FastAPI(
    title="Pirate Cinema",
    version=__version__.lstrip("v"),
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    body = "Unable to read request body"

    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError, ClientDisconnect, RuntimeError):
        logger.warning("Failed to read request body")
        try:
            raw_body = await request.body()
            body = raw_body.decode("utf-8")
        except (UnicodeDecodeError, AttributeError, ClientDisconnect, RuntimeError):
            logger.warning("Failed to decode request body")

    logger.warning("Validation error 422. Errors: %s. Sent Body: %s", errors, body)
    return JSONResponse(status_code=422, content={"detail": errors})


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    logger.warning("AppException %s: %s", exc.status_code, exc.message)
    record_diagnostic_error("api", exc.__class__.__name__, exc.message)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


# Подключение роутеров
app.include_router(diagnostics_router)
app.include_router(library_router)
app.include_router(library_direct_router)
app.include_router(collections_router)
app.include_router(history_router)
app.include_router(search_router)
app.include_router(online_router)
app.include_router(player_router)
app.include_router(settings_router)
app.include_router(updater_router)
app.include_router(window_router)
app.include_router(i18n_router)
app.include_router(posters_router)
app.include_router(posters_direct_router)

# Директория статики
static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
