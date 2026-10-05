"""Main entry point. Run with: python -m backend.main"""
import json
import logging
import os
import re
import shutil
import socket
import sys
import threading
import time
from contextlib import asynccontextmanager

import anyio
import uvicorn
import webview
from aiofiles import open
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import __version__
from backend.core.config import BASE_DIR
from backend.core.config import load_settings as _load_settings
from backend.services import tray
from backend.services.i18n import DEFAULT_LANG, TRANSLATIONS, t

from .api.routers.i18n import i18n_router
from .api.routers.library import library_router
from .api.routers.player import player_router
from .api.routers.search import search_router
from .api.routers.settings import settings_router
from .infrastructure.torrserver import process as torrserver_process
from .repositories import db

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
_window: webview.Window | None = None

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
        # На случай системных сбоев (например, нет прав на запуск бинарника)
        app.state.startup_error = f"Системная ошибка TorrServer: {e}"
        logger.error("[ERROR] TorrServer system error: %s", e)

    yield

    logger.info("[SHUTDOWN] Stopping TorrServer process...")
    await anyio.to_thread.run_sync(torrserver_process.stop)

app = FastAPI(title="Pirate Cinema", version=__version__.lstrip("v"), lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()

    try:
        body = await request.json()
    except json.JSONDecodeError:
        try:
            body = (await request.body()).decode("utf-8")
        except UnicodeDecodeError:
            body = "Unable to read request body"

    logger.exception("Validation error 422. Errors: %s. Sent Body: %s", errors, body)

    return JSONResponse(status_code=422, content={"detail": errors})

# Register all routers
app.include_router(library_router)
app.include_router(search_router)
app.include_router(player_router)
app.include_router(settings_router)
app.include_router(i18n_router)

# Serve frontend static files
static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
lang = _load_settings().get("language", DEFAULT_LANG)

# Copy favicon if available from old location
favicon_src = BASE_DIR / "public" / "favicon.png"
favicon_dst = static_dir / "favicon.png"
if favicon_src.exists() and not favicon_dst.exists():
    shutil.copy2(favicon_src, favicon_dst)

@app.get("/")
async def root():
    if not (static_dir / "index.html").exists():
        raise FileNotFoundError(t("err_not_found"))
    async with open(static_dir / "index.html", "r", encoding="utf-8") as f:
        html = await f.read()
    ts = time.time()
    
    def replace_t(m):
        return t(m.group(1), lang=lang)
    html = re.sub(r'\{\{\s*t\([\'"]([^\'"]+)[\'"]\)\s*\}\}', replace_t, html)
    
    i18n_script = f"""
    <script>
    window.I18N = {json.dumps(TRANSLATIONS)};
    window.LANG = "{lang}";
    window.t = function(k, args) {{
        let text = (window.I18N[window.LANG] || {{}})[k] || (window.I18N["en"] || {{}})[k] || k;
        if (args) {{
            for (let key in args) {{
                text = text.replace("{{" + key + "}}", args[key]);
            }}
        }}
        return text;
    }};
    </script>
    </head>"""
    
    html = html.replace('</head>', i18n_script)
    html = re.sub(r'src="/static/app\.js[^"]*"', f'src="/static/app.js?v={ts}"', html)
    html = re.sub(r'href="/static/style\.css[^"]*"', f'href="/static/style.css?v={ts}"', html)
    return HTMLResponse(content=html, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="warning"))

def run_server():
    server.run()

def wait_for_port(port, timeout=10.0):
    start = time.time()
    while time.time() - start < timeout:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('127.0.0.1', port)) == 0:
                return True
        time.sleep(0.1)
    return False

def run_app():
    tr = threading.Thread(target=run_server, daemon=True)
    tr.start()
    
    if not wait_for_port(8000):
        print("Error: Server failed to start on port 8000")
        sys.exit(1)

    def on_tray_show():
        if _window:
            def _force_show():
                try:
                    _window.show()
                    _window.restore()
                except NameError:
                    logger.exception("Failed to show window from tray thread")

            threading.Thread(target=_force_show, daemon=True).start()

    def on_tray_exit():
        logger.info("[TRAY] Exit clicked. Closing window and stopping server...")

        server.should_exit = True
        torrserver_process.stop()
        tray.stop_tray()

        os._exit(0)

    global _window
    _window = webview.create_window(
        'Pirate Cinema',
        'http://127.0.0.1:8000',
        width=1280,
        height=800,
        background_color='#141414'
    )

    def initialize_tray():
        icon_path = static_dir / "favicon.png"

        tray.start_tray(
            icon_path=icon_path,
            on_show=on_tray_show,
            on_exit=on_tray_exit,
            show_text=t("tray_show", lang=lang),
            exit_text=t("tray_exit", lang=lang),
        )

    def on_closed():
        logger.info("[GUI] Window closed. Cleaning up resources...")
        tray.stop_tray()
        server.should_exit = True
        torrserver_process.stop()

    _window.events.closed += on_closed

    webview.start(initialize_tray)
    
    # Graceful shutdown
    tray.stop_tray()
    server.should_exit = True
    torrserver_process.stop()
    tr.join(timeout=3.0)
    os._exit(0)

if __name__ == "__main__":
    run_app()
