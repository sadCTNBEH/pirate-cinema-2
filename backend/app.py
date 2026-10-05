"""FastAPI Application Setup."""
import json
import logging
from contextlib import asynccontextmanager

import anyio
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import ClientDisconnect

from backend import __version__
from backend.api.routers.i18n import i18n_router
from backend.api.routers.library import library_router
from backend.api.routers.player import player_router
from backend.api.routers.search import search_router
from backend.api.routers.settings import settings_router
from backend.core.settings import BASE_DIR
from backend.infrastructure.torrserver import process as torrserver_process
from backend.repositories import db

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
    except OSError as e:
        app.state.startup_error = f"Системная ошибка TorrServer: {e}"
        logger.error("[ERROR] TorrServer system error: %s", e)

    yield

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


# Подключение роутеров
app.include_router(library_router)
app.include_router(search_router)
app.include_router(player_router)
app.include_router(settings_router)
app.include_router(i18n_router)

# Директория статики
static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
