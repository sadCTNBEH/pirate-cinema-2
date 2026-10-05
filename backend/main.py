"""Main entry point. Run with: python -m backend.main"""
import threading
from contextlib import asynccontextmanager
from pathlib import Path
import time
import sys

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from . import __version__
import webview

if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).parent.parent

from .api.routes import library_router, search_router, player_router, settings_router, i18n_router
from .services import db, torrserver_process

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Init DB
    db.init_db()



    # Start TorrServer if bundled binary exists
    try:
        torrserver_process.connect_or_start()
        app.state.startup_error = None
    except Exception as e:
        app.state.startup_error = f"Ошибка запуска TorrServer: {e}"
        print(f"[WARN] TorrServer: {e}")

    yield

    # Cleanup
    torrserver_process.stop()

app = FastAPI(title="Pirate Cinema", version=__version__, lifespan=lifespan)

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

# Copy favicon if available from old location
favicon_src = BASE_DIR / "public" / "favicon.png"
favicon_dst = static_dir / "favicon.png"
if favicon_src.exists() and not favicon_dst.exists():
    import shutil
    shutil.copy2(favicon_src, favicon_dst)

@app.get("/")
async def root():
    from fastapi.responses import HTMLResponse
    import time
    from backend.services.i18n import TRANSLATIONS, DEFAULT_LANG, t
    from backend.api.routes import _load_settings
    import json
    
    if not (static_dir / "index.html").exists():
        raise FileNotFoundError(t("err_not_found"))
    with open(static_dir / "index.html", "r", encoding="utf-8") as f:
        html = f.read()
    import re
    ts = time.time()
    
    lang = _load_settings().get("language", DEFAULT_LANG)
    
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
    import socket
    start = time.time()
    while time.time() - start < timeout:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('127.0.0.1', port)) == 0:
                return True
        time.sleep(0.1)
    return False

def run_app():
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    
    if not wait_for_port(8000):
        print("Error: Server failed to start on port 8000")
        sys.exit(1)

    window = webview.create_window(
        'Pirate Cinema', 
        'http://127.0.0.1:8000', 
        width=1280, 
        height=800, 
        background_color='#141414'
    )
    def on_closed():
        server.should_exit = True
        torrserver_process.stop()

    window.events.closed += on_closed

    webview.start()
    
    # Graceful shutdown
    server.should_exit = True
    torrserver_process.stop()
    t.join(timeout=3.0)

if __name__ == "__main__":
    run_app()
