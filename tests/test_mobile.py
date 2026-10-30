"""Targeted mobile transport, pairing and resume-session tests."""
import asyncio
import time
import unittest
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import deps
from backend.api.routers.remote import remote_router
from backend.models.playback import PlaybackState
from backend.repositories.db import Database
from backend.repositories.history import HistoryRepository
from backend.repositories.playback import PlaybackRepository
from backend.services.mobile import (
    MobileAccess,
    MobileSession,
    compatible,
    mobile_access,
)

HASH = 'a' * 40
FILE = {'id': 7, 'name': 'Show.S01E01.mp4', 'path': 'Show.S01E01.mp4', 'length': 10000000}
GOOD = {'format': {'format_name': 'mov,mp4,m4a,3gp,3g2,mj2'}, 'streams': [
    {'codec_type': 'video', 'codec_name': 'h264', 'pix_fmt': 'yuv420p', 'profile': 'High', 'level': 41},
    {'codec_type': 'audio', 'codec_name': 'aac', 'profile': 'LC', 'channels': 2}]}


def test_codec_gate():
    from copy import deepcopy
    assert compatible(GOOD)
    for path, value in [('format_name', 'matroska,webm'), ('codec_name', 'hevc'),
                        ('channels', 6), ('audio_codec', 'dts'), ('pix_fmt', 'yuv420p10le')]:
        data = deepcopy(GOOD)
        if path == 'format_name': data['format'][path] = value
        elif path == 'audio_codec': data['streams'][1]['codec_name'] = value
        elif path == 'channels': data['streams'][1][path] = value
        else: data['streams'][0][path] = value
        assert not compatible(data)


def test_progress_owner(tmp_path):
    db = Database(tmp_path / 'history.sqlite'); db.init_db()
    history, repo = HistoryRepository(db), PlaybackRepository(db)
    history.mark_played(HASH, 7, FILE['name'])
    pc = PlaybackState(HASH, 7, timecode=100, duration=1000)
    phone = PlaybackState(HASH, 7, timecode=300, duration=1000)
    repo.save_progress(phone)
    repo.save_progress(pc)
    assert repo.get_state(HASH, 7)['playback_timecode'] == 300
    newer_pc = PlaybackState(HASH, 7, timecode=400, duration=1000)
    repo.save_progress(newer_pc)
    repo.save_progress(replace(phone, timecode=350))
    assert repo.get_state(HASH, 7)['playback_timecode'] == 400
    history.mark_played(HASH, 7, FILE['name'])
    assert len(history.get_file_entry(HASH, 7)) > 0
    with db.get_connection() as conn:
        assert conn.execute('SELECT count(*) FROM media_file_history').fetchone()[0] == 1


class MobileTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.access = MobileAccess()
        self.app = FastAPI()
        self.app.add_api_route('/media/{token}', self.access.media, methods=['GET', 'HEAD'])
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app, client=('192.168.1.5', 123)), base_url='http://192.168.1.2')
        self.access.pairs['paired'] = ('192.168.1.5', time.monotonic() + 3600)
        self.client.cookies.set('pc_remote', 'paired')
        self.session = MobileSession('paired', '192.168.1.5', 'http://127.0.0.1:8090/selected', PlaybackState(HASH, 7), size=10)
        self.access.sessions['video'] = self.session

    async def asyncTearDown(self):
        await self.session.close()
        await self.client.aclose()

    async def test_range_head_416_cleanup(self):
        seen = []
        def upstream(req):
            seen.append(req)
            if req.headers.get('range') == 'bytes=99-':
                return httpx.Response(416, headers={'Content-Range':'bytes */10', 'Content-Length':'0'})
            return httpx.Response(206, headers={'Content-Range':'bytes 2-4/10', 'Content-Length':'3', 'Accept-Ranges':'bytes'}, stream=httpx.ByteStream(b'234'))
        real_client = httpx.AsyncClient
        with patch('backend.services.mobile.httpx.AsyncClient', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(upstream))):
            for method in ('GET', 'HEAD'):
                res = await self.client.request(method, '/media/video', headers={'Range':'bytes=2-4'})
                assert res.status_code == 206
                assert res.headers['content-range'] == 'bytes 2-4/10'
                assert res.headers['content-length'] == '3'
                assert res.headers['content-type'] == 'video/mp4'
                assert res.content == (b'234' if method == 'GET' else b'')
                assert not self.session.connections
            res = await self.client.get('/media/video', headers={'Range':'bytes=99-'})
            assert res.status_code == 416 and res.headers['content-range'] == 'bytes */10'
            res = await self.client.get('/media/video', headers={'Range':'bytes=1-2,4-5'})
            assert res.status_code == 416 and res.headers['content-range'] == 'bytes */10'
        assert all(r.url.path == '/selected' for r in seen)

    async def test_access_expiry_and_origin(self):
        assert (await self.client.get('/media/missing')).status_code == 403
        assert (await self.client.get('/media/video', headers={'Origin':'https://evil.example'})).status_code == 403
        self.client.cookies.clear()
        assert (await self.client.get('/media/video')).status_code == 401
        self.client.cookies.set('pc_remote', 'paired')
        self.session.expires = 0
        assert (await self.client.get('/media/video')).status_code == 403

    async def test_disconnect_closes_source(self):
        started = asyncio.Event()
        class SlowStream(httpx.AsyncByteStream):
            closed = False
            async def __aiter__(self):
                yield b'first'
                started.set()
                await asyncio.Event().wait()
            async def aclose(self):
                self.closed = True
        stream = SlowStream()
        real_client = httpx.AsyncClient
        with patch('backend.services.mobile.httpx.AsyncClient', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(lambda req: httpx.Response(200, stream=stream)))):
            task = asyncio.create_task(self.client.get('/media/video'))
            await asyncio.wait_for(started.wait(), 2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        assert stream.closed
        assert not self.session.connections
        assert self.session.slots._value == 4

    async def test_public_peer_denied(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app, client=('8.8.8.8', 1)), base_url='http://192.168.1.2') as c:
            assert (await c.get('/media/video')).status_code == 403

    async def test_upstream_redirect_or_range_ignored(self):
        real_client = httpx.AsyncClient
        for status in (302, 200, 500):
            with patch('backend.services.mobile.httpx.AsyncClient', side_effect=lambda status=status, **kw: real_client(transport=httpx.MockTransport(lambda req: httpx.Response(status)))):
                assert (await self.client.get('/media/video', headers={'Range':'bytes=2-'})).status_code == 502
            assert not self.session.connections


def test_mobile_launch_and_progress(tmp_path):
    app = FastAPI(); app.include_router(remote_router)
    db = Database(tmp_path / 'history.sqlite'); db.init_db()
    history, repo = HistoryRepository(db), PlaybackRepository(db)
    playback = MagicMock(select_torrent_file=AsyncMock(return_value={'file':FILE}))
    app.dependency_overrides[deps.get_playback_service] = lambda: playback
    app.dependency_overrides[deps.get_magnet_service] = lambda: MagicMock()
    app.dependency_overrides[deps.get_history_repo] = lambda: history
    app.dependency_overrides[deps.get_playback_repo] = lambda: repo
    app.dependency_overrides[deps.get_torrserver_url] = lambda: 'http://127.0.0.1:8090'
    mobile_access.pairs.clear(); mobile_access.sessions.clear()
    with TestClient(app, base_url='http://192.168.1.2', client=('192.168.1.5', 123)) as c:
        assert c.post('/api/remote/mobile', json={'hash':HASH}).status_code == 401
        assert c.get('/api/remote/info').status_code == 401
        assert c.post('/api/remote/pair', json={'code':'wrong'}).status_code == 403
        paired = c.post('/api/remote/pair', json={'code':mobile_access.code})
        assert paired.status_code == 200
        c.cookies.clear()
        c.headers['X-Remote-Token'] = paired.json()['token']
        history.mark_played(HASH, 7, FILE['name']); history.update_progress(HASH, 7, 123, 1000)
        with patch('backend.api.routers.remote.probe', new=AsyncMock()) as probe_mock, patch('backend.infrastructure.torrserver.client.require_ram_cache', new=AsyncMock()), patch('backend.infrastructure.torrserver.client.torrent_video_files', new=AsyncMock(return_value=[FILE])):
            response = c.post('/api/remote/mobile', json={'hash':HASH,'file_id':7})
            assert response.status_code == 200, response.text
            data = response.json(); assert data['resume'] == 123
            assert '8090' not in response.text
            assert 'index=7' in probe_mock.call_args.args[0]
            playback.launch.assert_not_called()
            url = '/api/remote/mobile/' + data['token'] + '/progress'
            assert c.post(url, json={'sequence':2,'position':300,'duration':1000}).status_code == 200
            c.post(url, json={'sequence':1,'position':100,'duration':1000})
            assert repo.get_state(HASH, 7)['playback_timecode'] == 300
            assert c.post(url, json={'sequence':3,'position':350,'duration':1000,'close':True}).status_code == 200
            assert data['token'] not in mobile_access.sessions
            assert c.get(data['url']).status_code == 403
    mobile_access.pairs.clear()
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import skipUnless

from backend.services.mobile import probe


@skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg tools are optional')
def test_real_mp4_probe_over_http():
    # The synthetic video exists only in stdout/RAM, never in a fixture file.
    video = subprocess.run([shutil.which('ffmpeg'), '-v','error','-f','lavfi','-i','color=c=black:s=160x90:r=24',
        '-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t','1','-c:v','libx264','-pix_fmt','yuv420p',
        '-profile:v','main','-level','3.1','-c:a','aac','-movflags','frag_keyframe+empty_moov',
        '-f','mp4','pipe:1'],capture_output=True,timeout=15,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),check=True).stdout
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            start = int(self.headers.get('Range','bytes=0-').split('=')[1].split('-')[0] or 0)
            body = video[start:]
            self.send_response(206 if 'Range' in self.headers else 200)
            self.send_header('Content-Type','video/mp4'); self.send_header('Content-Length',str(len(body)))
            self.send_header('Accept-Ranges','bytes')
            if 'Range' in self.headers: self.send_header('Content-Range',f'bytes {start}-{len(video)-1}/{len(video)}')
            self.end_headers(); self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        asyncio.run(probe(f'http://127.0.0.1:{server.server_port}/selected.mp4'))
    finally:
        server.shutdown();server.server_close();thread.join(timeout=2)
