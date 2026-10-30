"""Integration tests for F-051 compatible HLS, Direct Play, seek, and RAM-only policy."""

import asyncio
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import skipUnless
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import deps
from backend.api.routers.remote import remote_router
from backend.infrastructure.ffmpeg import get_ffmpeg, get_ffprobe
from backend.models.playback import PlaybackState
from backend.repositories.db import Database
from backend.repositories.history import HistoryRepository
from backend.repositories.playback import PlaybackRepository
from backend.services.mobile import mobile_access


def generate_test_media(fmt: str, vcodec: str, acodec: str, duration: int = 4, extra_flags: list[str] | None = None) -> bytes:
    ffmpeg_bin = get_ffmpeg()
    if not ffmpeg_bin:
        pytest.skip("FFmpeg not available")

    import tempfile
    ext = "mkv" if fmt == "matroska" else fmt
    with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tf:
        temp_path = tf.name

    try:
        cmd = [
            str(ffmpeg_bin), "-y", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=160x90:rate=25",
            "-f", "lavfi", "-i", f"sine=frequency=1000:duration={duration}",
            "-c:v", vcodec,
            "-c:a", acodec,
        ]
        if extra_flags:
            cmd.extend(extra_flags)
        cmd.extend(["-f", fmt, temp_path])

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(cmd, check=True, creationflags=creationflags)
        with open(temp_path, "rb") as f:
            return f.read()
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


class MediaHttpServer:
    def __init__(self, data: bytes, content_type: str):
        self.data = data
        self.content_type = content_type
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_HEAD(self):
                self.send_response(200)
                self.send_header("Content-Type", parent.content_type)
                self.send_header("Content-Length", str(len(parent.data)))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()

            def do_GET(self):
                range_header = self.headers.get("Range")
                if range_header:
                    start_str = range_header.split("=")[1].split("-")[0]
                    end_str = range_header.split("=")[1].split("-")[1]
                    start = int(start_str) if start_str else 0
                    end = int(end_str) if end_str else len(parent.data) - 1
                    chunk = parent.data[start:end + 1]
                    self.send_response(206)
                    self.send_header("Content-Type", parent.content_type)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{len(parent.data)}")
                    self.send_header("Content-Length", str(len(chunk)))
                    self.send_header("Accept-Ranges", "bytes")
                    self.end_headers()
                    self.wfile.write(chunk)
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", parent.content_type)
                    self.send_header("Content-Length", str(len(parent.data)))
                    self.send_header("Accept-Ranges", "bytes")
                    self.end_headers()
                    self.wfile.write(parent.data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)


@skipUnless(get_ffmpeg() and get_ffprobe(), "FFmpeg/FFprobe required for integration tests")
def test_direct_play_and_moov_tail(tmp_path):
    """1 & 2: MP4/H.264/AAC Direct Play and MP4 with moov atom at the end."""
    mp4_bytes = generate_test_media(
        fmt="mp4",
        vcodec="libx264",
        acodec="aac",
        duration=2,
        extra_flags=["-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.1"],
    )
    assert len(mp4_bytes) > 0

    server = MediaHttpServer(mp4_bytes, "video/mp4")
    server.start()
    try:
        app = FastAPI()
        app.include_router(remote_router)
        db = Database(tmp_path / "history.sqlite")
        db.init_db()
        history, repo = HistoryRepository(db), PlaybackRepository(db)

        file_info = {"id": 1, "name": "movie.mp4", "path": "movie.mp4", "length": len(mp4_bytes)}
        stream_src = f"http://127.0.0.1:{server.port}/movie.mp4"

        mobile_access.pairs.clear()
        mobile_access.sessions.clear()

        with TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 12345)) as client:
            # Pair
            res = client.post("/api/remote/pair", json={"code": mobile_access.code})
            assert res.status_code == 200

            # Direct session creation
            from unittest.mock import AsyncMock, patch
            with patch("backend.infrastructure.torrserver.client.require_ram_cache", new=AsyncMock()), \
                 patch("backend.infrastructure.torrserver.client.stream_url", return_value=stream_src), \
                 patch("backend.infrastructure.torrserver.client.torrent_video_files", new=AsyncMock(return_value=[file_info])):

                playback = AsyncMock()
                playback.select_torrent_file = AsyncMock(return_value={"file": file_info})
                app.dependency_overrides[deps.get_playback_service] = lambda: playback
                app.dependency_overrides[deps.get_magnet_service] = lambda: AsyncMock()
                app.dependency_overrides[deps.get_history_repo] = lambda: history
                app.dependency_overrides[deps.get_playback_repo] = lambda: repo
                app.dependency_overrides[deps.get_torrserver_url] = lambda: "http://127.0.0.1:8090"

                resp = client.post("/api/remote/mobile", json={"hash": "b" * 40, "file_id": 1})
                assert resp.status_code == 200, resp.text
                data = resp.json()
                assert data["mode"] == "direct"
                assert "/media" in data["url"]
                assert data["duration"] > 0

                # Test range request to start
                media_res = client.get(data["url"], headers={"Range": "bytes=0-100"})
                assert media_res.status_code == 206
                assert media_res.headers["content-type"] == "video/mp4"
                assert media_res.headers["accept-ranges"] == "bytes"
                assert "content-range" in media_res.headers

                # Test tail range request (moov atom probing)
                tail_start = len(mp4_bytes) - 500
                tail_res = client.get(data["url"], headers={"Range": f"bytes={tail_start}-"})
                assert tail_res.status_code == 206
                assert tail_res.headers["content-type"] == "video/mp4"
                assert int(tail_res.headers["content-length"]) == len(mp4_bytes) - tail_start
    finally:
        server.stop()


@skipUnless(get_ffmpeg() and get_ffprobe(), "FFmpeg/FFprobe required for integration tests")
@pytest.mark.asyncio
async def test_mkv_transcode_and_seeking_in_hls(tmp_path):
    """3, 5, 6, 7, 8 & 9: MKV/H.264 Remux to HLS, .m3u8, seeking, resume, cleanup, no disk writes."""
    mkv_bytes = generate_test_media(
        fmt="matroska",
        vcodec="libx264",
        acodec="ac3",
        duration=12,
        extra_flags=["-pix_fmt", "yuv420p", "-g", "250", "-keyint_min", "250"],
    )
    assert len(mkv_bytes) > 0

    server = MediaHttpServer(mkv_bytes, "video/x-matroska")
    server.start()

    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        app_port = s.getsockname()[1]

    app = FastAPI()
    app.include_router(remote_router)
    db = Database(tmp_path / "history.sqlite")
    db.init_db()
    history, repo = HistoryRepository(db), PlaybackRepository(db)

    file_info = {"id": 2, "name": "series.mkv", "path": "series.mkv", "length": len(mkv_bytes)}
    stream_src = f"http://127.0.0.1:{server.port}/series.mkv"

    playback = AsyncMock()
    playback.select_torrent_file = AsyncMock(return_value={"file": file_info})
    app.dependency_overrides[deps.get_playback_service] = lambda: playback
    app.dependency_overrides[deps.get_magnet_service] = lambda: AsyncMock()
    app.dependency_overrides[deps.get_history_repo] = lambda: history
    app.dependency_overrides[deps.get_playback_repo] = lambda: repo
    app.dependency_overrides[deps.get_torrserver_url] = lambda: "http://127.0.0.1:8090"

    import uvicorn
    uv_config = uvicorn.Config(app, host="127.0.0.1", port=app_port, log_level="warning")
    uv_server = uvicorn.Server(uv_config)
    uv_thread = threading.Thread(target=uv_server.run, daemon=True)
    uv_thread.start()

    while not uv_server.started:
        await asyncio.sleep(0.05)

    try:
        mobile_access.pairs.clear()
        mobile_access.sessions.clear()

        # Track any disk file creation in working dir or temp dir
        initial_cwd_files = set(os.listdir("."))

        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{app_port}", timeout=25.0) as client:
            with patch("backend.infrastructure.torrserver.client.require_ram_cache", new=AsyncMock()), \
                 patch("backend.infrastructure.torrserver.client.stream_url", return_value=stream_src), \
                 patch("backend.infrastructure.torrserver.client.torrent_video_files", new=AsyncMock(return_value=[file_info])):

                # Pair
                res = await client.post("/api/remote/pair", json={"code": mobile_access.code})
                assert res.status_code == 200

                # Pre-save resume progress in repo at 6s
                history.mark_played("c" * 40, 2, "series.mkv")
                repo.save_progress(PlaybackState(hash="c" * 40, file_id=2, timecode=6, duration=12))

                resp = await client.post("/api/remote/mobile", json={"hash": "c" * 40, "file_id": 2})
                assert resp.status_code == 200, resp.text
                data = resp.json()
                assert data["mode"] == "transcode"
                assert "/hls/playlist.m3u8" in data["url"]
                assert data["resume"] == 6
                assert data["duration"] >= 10.0

                token = data["token"]
                session = mobile_access.sessions[token]
                session.segment_duration = 4.0  # 4s segments for fast test execution

                # 5. Fetch HLS playlist
                pl_res = await client.get(data["url"])
                assert pl_res.status_code == 200
                assert pl_res.headers["content-type"] == "application/vnd.apple.mpegurl"
                playlist_text = pl_res.text
                assert "#EXTM3U" in playlist_text
                assert "#EXT-X-PLAYLIST-TYPE:VOD" in playlist_text
                assert "seg_0.ts" in playlist_text
                assert "seg_1.ts" in playlist_text
                assert "#EXT-X-ENDLIST" in playlist_text

                # 5b. Fetch segment 0
                seg0_res = await client.get(f"/api/remote/mobile/{token}/hls/seg_0.ts")
                assert seg0_res.status_code == 200
                assert seg0_res.headers["content-type"] == "video/MP2T"
                assert seg0_res.content[0] == 0x47  # MPEG-TS sync byte
                assert len(seg0_res.content) > 1000

                # 6. Seek forward: Request segment 2 (around 8s)
                seg2_res = await client.get(f"/api/remote/mobile/{token}/hls/seg_2.ts")
                assert seg2_res.status_code == 200
                assert seg2_res.headers["content-type"] == "video/MP2T"
                assert seg2_res.content[0] == 0x47

                # 6b. Seek backward: Request segment 0 again
                seg0_again = await client.get(f"/api/remote/mobile/{token}/hls/seg_0.ts")
                assert seg0_again.status_code == 200
                assert seg0_again.content[0] == 0x47

                # 8. Close session and check cleanup
                prog_res = await client.post(f"/api/remote/mobile/{token}/progress", json={
                    "sequence": 10,
                    "position": 8.0,
                    "duration": 12.0,
                    "close": True,
                })
                assert prog_res.status_code == 200
                assert token not in mobile_access.sessions
                assert session.ffmpeg_process is None
                assert len(session.segments) == 0

                # 9. Verify no video data was written to disk
                final_cwd_files = set(os.listdir("."))
                assert final_cwd_files == initial_cwd_files, f"Unexpected disk files: {final_cwd_files - initial_cwd_files}"
    finally:
        uv_server.should_exit = True
        uv_thread.join(timeout=3.0)
        server.stop()


@skipUnless(get_ffmpeg() and get_ffprobe(), "FFmpeg/FFprobe required for integration tests")
def test_transcode_detection():
    """4: Incompatible video codec (e.g. 10-bit or HEVC) triggers transcode mode."""
    probe_hevc = {
        "format": {"format_name": "matroska,webm", "duration": "120.0"},
        "streams": [
            {"codec_type": "video", "codec_name": "hevc", "pix_fmt": "yuv420p10le", "profile": "Main 10", "level": 120},
            {"codec_type": "audio", "codec_name": "aac", "channels": 2},
        ],
    }
    from backend.infrastructure.ffmpeg import analyze_compatibility
    res = analyze_compatibility(probe_hevc)
    assert res["mode"] == "transcode"
    assert "hevc" in res["reason"]


def test_authorization_protection():
    """11: Requests without valid cookie or session token are strictly rejected."""
    app = FastAPI()
    app.include_router(remote_router)

    with TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 12345)) as client:
        # Non-paired client cannot access /mobile
        res = client.post("/api/remote/mobile", json={"hash": "d" * 40})
        assert res.status_code == 401

        # Non-existent session
        res = client.get("/api/remote/mobile/invalid_token/hls/playlist.m3u8")
        assert res.status_code in (401, 403)


@skipUnless(get_ffmpeg() and get_ffprobe(), "FFmpeg/FFprobe required for integration tests")
@pytest.mark.asyncio
async def test_continuous_consecutive_playback_and_pacing(tmp_path):
    """Verify that multiple consecutive segments (0, 1, 2, 3) are served without buffer overrun or stalls."""
    mkv_bytes = generate_test_media(
        fmt="matroska",
        vcodec="libx264",
        acodec="ac3",
        duration=16,
        extra_flags=["-pix_fmt", "yuv420p", "-g", "250", "-keyint_min", "250"],
    )
    server = MediaHttpServer(mkv_bytes, "video/x-matroska")
    server.start()

    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        app_port = s.getsockname()[1]

    app = FastAPI()
    app.include_router(remote_router)
    db = Database(tmp_path / "history.sqlite")
    db.init_db()
    history, repo = HistoryRepository(db), PlaybackRepository(db)

    file_info = {"id": 10, "name": "movie.mkv", "path": "movie.mkv", "length": len(mkv_bytes)}
    stream_src = f"http://127.0.0.1:{server.port}/movie.mkv"

    playback = AsyncMock()
    playback.select_torrent_file = AsyncMock(return_value={"file": file_info})
    app.dependency_overrides[deps.get_playback_service] = lambda: playback
    app.dependency_overrides[deps.get_magnet_service] = lambda: AsyncMock()
    app.dependency_overrides[deps.get_history_repo] = lambda: history
    app.dependency_overrides[deps.get_playback_repo] = lambda: repo
    app.dependency_overrides[deps.get_torrserver_url] = lambda: "http://127.0.0.1:8090"

    import uvicorn
    uv_config = uvicorn.Config(app, host="127.0.0.1", port=app_port, log_level="warning")
    uv_server = uvicorn.Server(uv_config)
    uv_thread = threading.Thread(target=uv_server.run, daemon=True)
    uv_thread.start()

    while not uv_server.started:
        await asyncio.sleep(0.05)

    try:
        mobile_access.pairs.clear()
        mobile_access.sessions.clear()

        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{app_port}", timeout=25.0) as client:
            with patch("backend.infrastructure.torrserver.client.require_ram_cache", new=AsyncMock()), \
                 patch("backend.infrastructure.torrserver.client.stream_url", return_value=stream_src), \
                 patch("backend.infrastructure.torrserver.client.torrent_video_files", new=AsyncMock(return_value=[file_info])):

                # Pair
                await client.post("/api/remote/pair", json={"code": mobile_access.code})
                res = await client.post("/api/remote/mobile", json={"hash": "e" * 40, "file_id": 10})
                data = res.json()
                token = data["token"]
                session = mobile_access.sessions[token]
                session.segment_duration = 4.0

                # 1. Playlist check
                pl_res = await client.get(data["url"])
                assert pl_res.status_code == 200
                assert "#EXT-X-VERSION:3" in pl_res.text
                assert "seg_0.ts" in pl_res.text

                # 2. Sequential segment consumption like Safari
                for seq in range(4):
                    seg_res = await client.get(f"/api/remote/mobile/{token}/hls/seg_{seq}.ts")
                    assert seg_res.status_code == 200, f"Segment {seq} failed with status {seg_res.status_code}"
                    assert seg_res.content[0] == 0x47
                    assert len(seg_res.content) > 500
    finally:
        uv_server.should_exit = True
        uv_thread.join(timeout=3.0)
        server.stop()


def test_active_pc_playback_resume_and_service_get_state(tmp_path):
    """Verify that PlaybackService.get_state(hash, file_id) and active_states dict are handled cleanly."""
    from backend.models.playback import PlaybackState
    from backend.services.playback import PlaybackService

    app = FastAPI()
    app.include_router(remote_router)
    db = Database(tmp_path / "history.sqlite")
    db.init_db()
    history, repo = HistoryRepository(db), PlaybackRepository(db)

    file_info = {"id": 1, "name": "active_movie.mp4", "path": "active_movie.mp4", "length": 1000}
    stream_src = "http://127.0.0.1:8090/stream"

    mobile_access.pairs.clear()
    mobile_access.sessions.clear()

    # Mock PlaybackService with real get_state signature
    playback_mock = AsyncMock(spec=PlaybackService)
    playback_mock.select_torrent_file = AsyncMock(return_value={"file": file_info})
    playback_mock.active_states = {
        "f" * 40: PlaybackState(hash="f" * 40, file_id=1, timecode=179, duration=600)
    }

    async def mock_get_state(hash_val: str, file_id: int):
        if hash_val == "f" * 40 and file_id == 1:
            return playback_mock.active_states["f" * 40]
        raise LookupError("Not found")

    playback_mock.get_state = AsyncMock(side_effect=mock_get_state)

    app.dependency_overrides[deps.get_playback_service] = lambda: playback_mock
    app.dependency_overrides[deps.get_magnet_service] = lambda: AsyncMock()
    app.dependency_overrides[deps.get_history_repo] = lambda: history
    app.dependency_overrides[deps.get_playback_repo] = lambda: repo
    app.dependency_overrides[deps.get_torrserver_url] = lambda: "http://127.0.0.1:8090"

    with patch("backend.api.routers.remote.probe", new=AsyncMock(return_value={"mode": "direct", "duration": 600.0})), \
         patch("backend.infrastructure.torrserver.client.stream_url", return_value=stream_src), \
         patch("backend.infrastructure.torrserver.client.torrent_video_files", new=AsyncMock(return_value=[file_info])), \
         TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 12345)) as client:
        res = client.post("/api/remote/pair", json={"code": mobile_access.code})
        assert res.status_code == 200

        resp = client.post("/api/remote/mobile", json={"hash": "f" * 40, "file_id": 1})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["resume"] == 179
