"""FastAPI Application Setup."""

import asyncio
import ipaddress
import json
import logging
import socket
import sys
import zipfile
from contextlib import asynccontextmanager
from urllib.parse import urlparse

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
from backend.api.routers.remote import remote_router
from backend.api.routers.search import search_router
from backend.api.routers.settings import settings_router
from backend.api.routers.updater import updater_router
from backend.api.routers.window import window_router
from backend.core.settings import BASE_DIR, get_data_dir, get_torrserver_url
from backend.exceptions import AppException
from backend.infrastructure.asyncio_errors import windows_transport_cleanup
from backend.infrastructure.torrserver import process as torrserver_process
from backend.repositories import db
from backend.services.diagnostics import record_diagnostic_error

logger = logging.getLogger(__name__)


@asynccontextmanager
async def application_lifespan(app: FastAPI):
    from backend.services.mobile import mobile_access
    mobile_access.enable_persistence(get_data_dir() / 'remote-pairs.json')
    db.init_db()
    torrserver_process.start_monitor()
    try:
        await anyio.to_thread.run_sync(torrserver_process.connect_or_start, get_torrserver_url())
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

    for session in list(mobile_access.sessions.values()):
        await session.close()
    mobile_access.sessions.clear()

    logger.info("[SHUTDOWN] Stopping player processes...")
    await anyio.to_thread.run_sync(torrserver_process.shutdown_monitor)
    try:
        from backend.api.deps import get_playback_service

        await get_playback_service().stop_all()
    except (OSError, RuntimeError, AttributeError, ValueError) as e:
        logger.warning("Failed to stop playback service on shutdown: %s", e, exc_info=True)

    logger.info("[SHUTDOWN] Awaiting background metadata tasks...")
    try:
        from backend.api.deps import get_metadata_service

        await get_metadata_service().shutdown(timeout=3.0)
    except (asyncio.TimeoutError, OSError, RuntimeError, AttributeError) as e:
        logger.warning("Failed to shutdown metadata service tasks: %s", e, exc_info=True)

    logger.info("[SHUTDOWN] Closing online service...")
    try:
        from backend.api.deps import get_online_service

        await get_online_service().close()
    except (RuntimeError, OSError) as e:
        logger.warning("Failed to close online service on shutdown: %s", e)

    logger.info("[SHUTDOWN] Stopping TorrServer process...")
    await anyio.to_thread.run_sync(torrserver_process.stop)


@asynccontextmanager
async def lifespan(app: FastAPI):
    with windows_transport_cleanup(asyncio.get_running_loop()):
        async with application_lifespan(app):
            yield


app = FastAPI(
    title="Pirate Cinema",
    version=__version__.lstrip("v"),
    lifespan=lifespan,
)

DANGEROUS_DESKTOP_PREFIXES = (
    "/api/settings",
    "/api/updater",
    "/api/diagnostics",
)
DANGEROUS_DESKTOP_EXACT = (
    "/api/window/close",
)


def _is_loopback_client(host: str | None) -> bool:
    if not host or host in ("127.0.0.1", "::1", "localhost", "testclient", "test"):
        return True
    try:
        addr = ipaddress.ip_address(host)
        if getattr(addr, "ipv4_mapped", None):
            addr = addr.ipv4_mapped
        return addr.is_loopback
    except (ValueError, AttributeError):
        return False


def _is_lan_client(host: str | None) -> bool:
    if not host:
        return False
    if host in ("testclient", "testserver", "test"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        if getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped
        if ip.is_loopback:
            return True
        return any(
            ip in ipaddress.ip_network(n)
            for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7", "fe80::/10")
            if ip.version == ipaddress.ip_network(n).version
        )
    except (ValueError, AttributeError):
        return False


def _is_allowed_host(host_header: str | None) -> bool:
    if not host_header:
        return True
    raw_host = host_header.strip().lower()
    if raw_host.startswith("["):
        end_bracket = raw_host.find("]")
        hostname = raw_host[1:end_bracket] if end_bracket != -1 else raw_host.split(":")[0]
    else:
        hostname = raw_host.split(":")[0]

    if hostname in ("localhost", "127.0.0.1", "::1", "testserver", "testclient", "test"):
        return True

    try:
        local_name = socket.gethostname().strip().lower().removesuffix(".local")
        if hostname in (local_name, f"{local_name}.local"):
            return True
    except OSError:
        pass

    if hostname.endswith(".local"):
        return True

    try:
        addr = ipaddress.ip_address(hostname)
        if getattr(addr, "ipv4_mapped", None):
            addr = addr.ipv4_mapped
        return addr.is_loopback or addr.is_private or addr.is_link_local
    except ValueError:
        pass

    return False


def _is_allowed_origin(origin: str, request: Request) -> bool:
    if not origin:
        return True
    if origin == "null":
        client_host = request.client.host if request.client else None
        return _is_loopback_client(client_host)
    base_url = str(request.base_url).rstrip("/")
    if origin.rstrip("/") == base_url:
        return True
    try:
        parsed = urlparse(origin)
        hostname = parsed.hostname
        if hostname and _is_allowed_host(hostname):
            return True
    except Exception:
        pass
    return False


@app.middleware("http")
async def lan_security_middleware(request: Request, call_next):
    # 1. DNS rebinding protection: validate Host header
    host_header = request.headers.get("host")
    if not _is_allowed_host(host_header):
        return JSONResponse(
            status_code=403,
            content={"detail": "Недопустимый хост (защита от DNS rebinding)"},
        )

    # 2. Check Origin / Sec-Fetch-Site for API endpoints
    path = request.url.path
    if request.method != "OPTIONS" and path.startswith("/api/"):
        origin = request.headers.get("origin")
        if origin and not _is_allowed_origin(origin, request):
            return JSONResponse(
                status_code=403,
                content={"detail": "Недопустимый источник запроса (Origin)"},
            )
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse(
                status_code=403,
                content={"detail": "Недопустимый источник запроса (cross-site)"},
            )

    client_host = request.client.host if request.client else None
    is_local = _is_loopback_client(client_host)

    # 3. Deny non-local requests if LAN/Remote API is globally disabled
    from backend.core.settings import config
    remote_enabled = getattr(config, "REMOTE_ENABLED", True)
    if not is_local and not remote_enabled:
        return JSONResponse(
            status_code=403,
            content={"detail": "Удалённый доступ к API отключён"},
        )

    # 4. Block dangerous desktop APIs from LAN/public peers
    if not is_local:
        clean_path = path.rstrip("/")
        is_dangerous = (
            any(clean_path == prefix or clean_path.startswith(prefix + "/") for prefix in DANGEROUS_DESKTOP_PREFIXES)
            or clean_path in DANGEROUS_DESKTOP_EXACT
        )
        if is_dangerous:
            return JSONResponse(
                status_code=403,
                content={"detail": "Доступ к desktop API запрещён из локальной сети"},
            )

        if not _is_lan_client(client_host):
            return JSONResponse(
                status_code=403,
                content={"detail": "Доступ разрешён только из локальной сети"},
            )

    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    if request.url.path.startswith('/api/remote/'):
        # Pairing capabilities, magnets and media tokens must not enter diagnostics.
        return JSONResponse(status_code=422, content={'detail': 'Некорректный запрос веб-пульта'})
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
app.include_router(remote_router)
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
