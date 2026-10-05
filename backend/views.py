"""Root page HTML renderer."""

import json
import re
import shutil
import time

from aiofiles import open
from fastapi import HTTPException
from fastapi.responses import HTMLResponse

from backend.app import app, static_dir
from backend.core.settings import BASE_DIR
from backend.core.settings import load_settings as _load_settings
from backend.services.i18n import DEFAULT_LANG, TRANSLATIONS, t

# Копирование favicon при импорте
favicon_src = BASE_DIR / "public" / "favicon.png"
favicon_dst = static_dir / "favicon.png"
if favicon_src.exists() and not favicon_dst.exists():
    shutil.copy2(favicon_src, favicon_dst)


@app.get("/", response_class=HTMLResponse)
async def root():
    index_path = static_dir / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail=t("err_not_found"))

    lang = _load_settings().get("language", DEFAULT_LANG)

    async with open(index_path, "r", encoding="utf-8") as f:
        html = await f.read()

    ts = time.time()

    html = re.sub(
        r'\{\{\s*t\([\'"]([^\'"]+)[\'"]\)\s*\}\}',
        lambda m: t(m.group(1), lang=lang),
        html,
    )

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
    html = re.sub(r'src="/static/app\.js[^"]*"', f'src="/static/app.js?v={ts}"', html)
    html = re.sub(r'href="/static/style\.css[^"]*"', f'href="/static/style.css?v={ts}"', html)

    return HTMLResponse(
        content=html,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )
