"""Local real-media fixture for mobile_playback_ui.cjs (no TorrServer required)."""
import secrets
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend.api import deps
from backend.api.routers.remote import remote_router
from backend.infrastructure.ffmpeg import get_ffmpeg
from backend.infrastructure.torrserver import client as ts
from backend.models.playback import PlaybackState
from backend.repositories.db import Database
from backend.repositories.history import HistoryRepository
from backend.repositories.playback import PlaybackRepository
from backend.services.mobile import mobile_access
from backend.services.remote_html import REMOTE_HTML


def main():
    with tempfile.TemporaryDirectory(prefix='pc-mobile-ui-') as directory:
        root = Path(directory)
        mobile_access.enable_persistence(root / 'remote-pairs.json')
        media = root / 'movie.mkv'
        subprocess.run([
            str(get_ffmpeg()), '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=160x90:rate=25',
            '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '54', '-c:v', 'libx264',
            '-pix_fmt', 'yuv420p', '-g', '250', '-sc_threshold', '0', '-c:a', 'ac3', str(media),
        ], check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        app = FastAPI()
        app.include_router(remote_router)
        app.mount('/static', StaticFiles(directory='static'))
        app.add_api_route('/fixture.mkv', lambda: FileResponse(media), methods=['GET', 'HEAD'])
        app.add_api_route('/remote', lambda: HTMLResponse(REMOTE_HTML))
        app.add_api_route('/health', lambda: {'ready': True, 'code': mobile_access.code})
        def simulate_restart():
            mobile_access.pairs.clear()
            mobile_access.code = secrets.token_urlsafe(24)
            mobile_access.enable_persistence(root / 'remote-pairs.json')
            return {'restarted': True}
        app.add_api_route('/simulate-restart', simulate_restart, methods=['POST'])
        hash_ = 'a' * 40
        # Omit sizes: these short synthetic episodes would otherwise be classified as samples.
        file = {'id': 1, 'name': 'Show.S01E01.mkv'}
        following = {'id': 2, 'name': 'Show.S01E02.mkv'}
        state = PlaybackState(hash_, 1, timecode=9, duration=54, file_name='movie.mkv', is_ready=True)
        async def select_file(hash_, **kwargs):
            return {'file': following if kwargs.get('file_id') == 2 else file}
        playback = MagicMock(active_states={hash_: state}, select_torrent_file=AsyncMock(side_effect=select_file))
        db = Database(root / 'history.sqlite')
        db.init_db()
        history, repo = HistoryRepository(db), PlaybackRepository(db)
        app.dependency_overrides[deps.get_playback_service] = lambda: playback
        app.dependency_overrides[deps.get_magnet_service] = lambda: MagicMock()
        app.dependency_overrides[deps.get_history_repo] = lambda: history
        app.dependency_overrides[deps.get_playback_repo] = lambda: repo
        ts.require_ram_cache = AsyncMock()
        ts.torrent_video_files = AsyncMock(return_value=[file, following])
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        ts.stream_url = lambda *args: f'http://127.0.0.1:{port}/fixture.mkv'
        print(port, flush=True)
        uvicorn.Server(uvicorn.Config(app, log_level='warning', access_log=False)).run(sockets=[sock])


if __name__ == '__main__':
    main()
