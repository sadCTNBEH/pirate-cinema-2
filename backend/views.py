"""Root page and static assets renderer."""

import json
import shutil
from pathlib import Path

from aiofiles import open
from fastapi import HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app import app, static_dir
from backend.core.settings import BASE_DIR
from backend.core.settings import load_settings
from backend.services.i18n import DEFAULT_LANG, TRANSLATIONS, t


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
    version_file = BASE_DIR.parent / "version.json"

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
    if favicon_dst.exists():
        return FileResponse(favicon_dst, media_type="image/png")
    if favicon_src.exists():
        return FileResponse(favicon_src, media_type="image/png")
    raise HTTPException(status_code=404, detail="favicon not found")


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