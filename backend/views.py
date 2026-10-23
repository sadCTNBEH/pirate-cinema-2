"""Root page and static assets renderer."""

import json
import shutil

from aiofiles import open
from fastapi import HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend.app import app, static_dir
from backend.core.settings import BASE_DIR, load_settings
from backend.services.i18n import DEFAULT_LANG, TRANSLATIONS

favicon_src = BASE_DIR / "public" / "favicon.png"
favicon_dst = static_dir / "favicon.png"
if favicon_src.exists() and not favicon_dst.exists():
    static_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(favicon_src, favicon_dst)

assets_dir = static_dir / "assets"
assets_dir.mkdir(parents=True, exist_ok=True)
app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


@app.get("/version.json")
async def get_version():
    version_file = BASE_DIR / "version.json"
    if not version_file.exists():
        version_file = BASE_DIR.parent / "version.json"
    if not version_file.exists():
        version_file = static_dir / "version.json"

    if version_file.exists():
        return FileResponse(
            version_file,
            media_type="application/json",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )
    raise HTTPException(status_code=404, detail="version.json not found")


@app.get("/static/favicon.png")
@app.get("/favicon.png")
async def get_favicon():
    if (static_dir / "favicon.png").exists():
        return FileResponse(static_dir / "favicon.png", media_type="image/png")
    if (BASE_DIR / "assets" / "brand" / "favicon.png").exists():
        return FileResponse(BASE_DIR / "assets" / "brand" / "favicon.png", media_type="image/png")
    raise HTTPException(status_code=404, detail="favicon not found")


@app.get("/static/favicon.ico")
@app.get("/favicon.ico")
async def get_favicon_ico():
    if (static_dir / "favicon.ico").exists():
        return FileResponse(static_dir / "favicon.ico", media_type="image/x-icon")
    if (BASE_DIR / "assets" / "brand" / "favicon.ico").exists():
        return FileResponse(BASE_DIR / "assets" / "brand" / "favicon.ico", media_type="image/x-icon")
    raise HTTPException(status_code=404, detail="favicon.ico not found")


@app.get("/static/logo.png")
@app.get("/logo.png")
async def get_logo():
    if (static_dir / "logo.png").exists():
        return FileResponse(static_dir / "logo.png", media_type="image/png")
    if (BASE_DIR / "assets" / "brand" / "logo.png").exists():
        return FileResponse(BASE_DIR / "assets" / "brand" / "logo.png", media_type="image/png")
    raise HTTPException(status_code=404, detail="logo not found")


@app.get("/static/icon.png")
@app.get("/icon.png")
async def get_icon():
    if (static_dir / "icon.png").exists():
        return FileResponse(static_dir / "icon.png", media_type="image/png")
    if (BASE_DIR / "assets" / "brand" / "icon.png").exists():
        return FileResponse(BASE_DIR / "assets" / "brand" / "icon.png", media_type="image/png")
    raise HTTPException(status_code=404, detail="icon not found")


@app.get("/apple-touch-icon.png")
@app.get("/apple-touch-icon-precomposed.png")
@app.get("/static/apple-touch-icon.png")
@app.get("/static/apple-touch-icon-precomposed.png")
async def get_apple_touch_icon():
    return await get_logo()


@app.get("/remote.webmanifest")
@app.get("/manifest.json")
@app.get("/static/remote.webmanifest")
async def get_remote_webmanifest():
    return {
        "name": "Pirate Cinema Remote",
        "short_name": "Pirate Cinema Remote",
        "description": "Пульт дистанционного управления и поиск торрентов Pirate Cinema",
        "start_url": "/remote",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait-primary",
        "background_color": "#06080d",
        "theme_color": "#06080d",
        "icons": [
            {
                "src": "/logo.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable",
            },
            {
                "src": "/logo.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable",
            },
        ],
    }


@app.get("/", response_class=HTMLResponse)
async def root():
    index_path = static_dir / "index.html"
    if not index_path.exists():
        raise HTTPException(
            status_code=404,
            detail="index.html not found. Соберите фронтенд: cd frontend && npm run build",
        )

    lang = load_settings().get("language", DEFAULT_LANG)

    async with open(index_path, "r", encoding="utf-8") as f:
        html = await f.read()

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

    html = html.replace("</head>", i18n_script)

    return HTMLResponse(
        content=html,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/remote", response_class=HTMLResponse)
async def get_remote_page():
    from backend.services.remote_html import REMOTE_HTML

    return HTMLResponse(
        content=REMOTE_HTML,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )
