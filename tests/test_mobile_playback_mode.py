"""Unit and router tests for mobile playback mode selection (Direct vs Remux vs HLS/Transcode).

Verifies:
1. Media analysis in infrastructure/ffmpeg.py (ffprobe metadata parsing).
2. Selection logic in services/mobile.py:
   - Direct Play for MP4/H.264/AAC;
   - Remux for MKV/H.264/AAC (container swap without heavy CPU transcoding);
   - HLS/Transcode for heavy/unsupported codecs (HEVC, 10-bit, AC3, DTS, 5.1, etc.).
3. Streaming response headers in api/routers/remote.py (Content-Type, Accept-Ranges).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI

from backend.api import deps
from backend.api.routers.remote import remote_router
from backend.infrastructure.ffmpeg import analyze_media
from backend.services.mobile import (
    compatible,
    mobile_access,
    select_playback_mode,
)

# ---------------------------------------------------------------------------
# Mock ffprobe data fixtures
# ---------------------------------------------------------------------------

MOCK_MP4_H264_AAC = {
    "format": {
        "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
        "duration": "142.500000",
    },
    "streams": [
        {
            "index": 0,
            "codec_type": "video",
            "codec_name": "h264",
            "pix_fmt": "yuv420p",
            "profile": "High",
            "level": 41,
            "duration": "142.500000",
        },
        {
            "index": 1,
            "codec_type": "audio",
            "codec_name": "aac",
            "channels": 2,
            "sample_rate": "48000",
            "duration": "142.500000",
        },
    ],
}

MOCK_MKV_H264_AAC = {
    "format": {
        "format_name": "matroska,webm",
        "duration": "3600.000000",
    },
    "streams": [
        {
            "index": 0,
            "codec_type": "video",
            "codec_name": "h264",
            "pix_fmt": "yuv420p",
            "profile": "High",
            "level": 41,
            "duration": "3600.000000",
        },
        {
            "index": 1,
            "codec_type": "audio",
            "codec_name": "aac",
            "channels": 2,
            "sample_rate": "48000",
            "duration": "3600.000000",
        },
    ],
}

MOCK_MKV_HEVC_AAC = {
    "format": {
        "format_name": "matroska,webm",
        "duration": "1800.0",
    },
    "streams": [
        {
            "index": 0,
            "codec_type": "video",
            "codec_name": "hevc",
            "pix_fmt": "yuv420p10le",
            "profile": "Main 10",
            "level": 120,
            "duration": "1800.0",
        },
        {
            "index": 1,
            "codec_type": "audio",
            "codec_name": "aac",
            "channels": 2,
        },
    ],
}

MOCK_MKV_H264_AC3 = {
    "format": {
        "format_name": "matroska",
        "duration": "2400.0",
    },
    "streams": [
        {
            "index": 0,
            "codec_type": "video",
            "codec_name": "h264",
            "pix_fmt": "yuv420p",
            "profile": "High",
            "level": 41,
        },
        {
            "index": 1,
            "codec_type": "audio",
            "codec_name": "ac3",
            "channels": 6,
        },
    ],
}

MOCK_MKV_H264_DTS = {
    "format": {
        "format_name": "matroska",
        "duration": "1200.0",
    },
    "streams": [
        {
            "index": 0,
            "codec_type": "video",
            "codec_name": "h264",
            "pix_fmt": "yuv420p",
            "profile": "Main",
            "level": 31,
        },
        {
            "index": 1,
            "codec_type": "audio",
            "codec_name": "dts",
            "channels": 6,
        },
    ],
}

MOCK_MP4_H264_10BIT = {
    "format": {
        "format_name": "mov,mp4",
        "duration": "500.0",
    },
    "streams": [
        {
            "index": 0,
            "codec_type": "video",
            "codec_name": "h264",
            "pix_fmt": "yuv420p10le",
            "profile": "High 10",
            "level": 50,
        },
        {
            "index": 1,
            "codec_type": "audio",
            "codec_name": "aac",
            "channels": 2,
        },
    ],
}

MOCK_NO_VIDEO = {
    "format": {
        "format_name": "mp3",
        "duration": "60.0",
    },
    "streams": [
        {
            "index": 0,
            "codec_type": "audio",
            "codec_name": "mp3",
            "channels": 2,
        },
    ],
}


# ---------------------------------------------------------------------------
# 1. Media Analysis Tests (infrastructure/ffmpeg.py)
# ---------------------------------------------------------------------------

def test_analyze_media_mp4():
    """Verify that analyze_media correctly extracts container and stream properties from MP4."""
    info = analyze_media(MOCK_MP4_H264_AAC)
    assert info["container"] == "mp4"
    assert info["is_mp4"] is True
    assert info["is_mkv"] is False
    assert info["video_codec"] == "h264"
    assert info["audio_codec"] == "aac"
    assert info["pix_fmt"] == "yuv420p"
    assert info["profile"] == "High"
    assert info["level"] == 41
    assert info["channels"] == 2
    assert info["duration"] == 142.5
    assert info["has_video"] is True
    assert info["has_audio"] is True


def test_analyze_media_mkv():
    """Verify that analyze_media correctly identifies MKV container."""
    info = analyze_media(MOCK_MKV_H264_AAC)
    assert info["container"] == "mkv"
    assert info["is_mp4"] is False
    assert info["is_mkv"] is True
    assert info["video_codec"] == "h264"
    assert info["audio_codec"] == "aac"
    assert info["duration"] == 3600.0


def test_analyze_media_tagged_duration():
    """Verify duration parsing from stream tags DURATION when format duration is missing."""
    data = {
        "format": {"format_name": "matroska"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "start_time": "0.05",
                "tags": {"DURATION": "01:30:15.500000000"},
            },
        ],
    }
    info = analyze_media(data)
    expected_sec = 3600 + 30 * 60 + 15.5 - 0.05
    assert abs(info["duration"] - expected_sec) < 0.01


# ---------------------------------------------------------------------------
# 2. Playback Mode Selection Tests (services/mobile.py & infrastructure/ffmpeg.py)
# ---------------------------------------------------------------------------

def test_mode_selection_direct_play():
    """MP4 with 8-bit H.264 and AAC stereo selects Direct Play."""
    res = select_playback_mode(MOCK_MP4_H264_AAC)
    assert res["mode"] == "direct"
    assert res["video_codec"] == "h264"
    assert res["audio_codec"] == "aac"
    assert "Direct Play" in res["reason"]
    assert compatible(MOCK_MP4_H264_AAC) is True


def test_mode_selection_remux():
    """MKV with 8-bit H.264 and AAC stereo selects Remux (no full transcode)."""
    res = select_playback_mode(MOCK_MKV_H264_AAC)
    assert res["mode"] == "remux"
    assert res["video_codec"] == "h264"
    assert res["audio_codec"] == "aac"
    assert "Remux" in res["reason"]
    # Remux is not direct play (requires container swap for Safari)
    assert compatible(MOCK_MKV_H264_AAC) is False


def test_mode_selection_transcode_hevc():
    """HEVC/H.265 in MKV selects Transcode mode."""
    res = select_playback_mode(MOCK_MKV_HEVC_AAC)
    assert res["mode"] == "transcode"
    assert res["video_codec"] == "hevc"
    assert "Transcode" in res["reason"]


def test_mode_selection_transcode_ac3():
    """MKV with AC3 audio selects Transcode mode (Safari lacks native AC3)."""
    res = select_playback_mode(MOCK_MKV_H264_AC3)
    assert res["mode"] == "transcode"
    assert res["audio_codec"] == "ac3"
    assert "Transcode" in res["reason"]


def test_mode_selection_transcode_dts():
    """MKV with DTS audio selects Transcode mode."""
    res = select_playback_mode(MOCK_MKV_H264_DTS)
    assert res["mode"] == "transcode"
    assert res["audio_codec"] == "dts"


def test_mode_selection_transcode_10bit_h264():
    """10-bit H.264 (yuv420p10le) selects Transcode even in MP4."""
    res = select_playback_mode(MOCK_MP4_H264_10BIT)
    assert res["mode"] == "transcode"
    assert compatible(MOCK_MP4_H264_10BIT) is False


def test_mode_selection_multichannel_audio():
    """H.264 with 6-channel audio (5.1 surround) selects Transcode for stereo downmix."""
    from copy import deepcopy
    data = deepcopy(MOCK_MP4_H264_AAC)
    data["streams"][1]["channels"] = 6
    res = select_playback_mode(data)
    assert res["mode"] == "transcode"


def test_mode_selection_unsupported_without_video():
    """Audio-only or corrupt probe with no video streams returns unsupported."""
    res = select_playback_mode(MOCK_NO_VIDEO)
    assert res["mode"] == "unsupported"
    assert "Видеопоток не обнаружен" in res["reason"]


# ---------------------------------------------------------------------------
# 3. Router Streaming Headers Tests (api/routers/remote.py)
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_remote_setup():
    """Configure a minimal FastAPI app with remote_router and mocked dependencies."""
    app = FastAPI()
    app.include_router(remote_router)

    mobile_access.pairs.clear()
    mobile_access.sessions.clear()

    # Pre-authorize a test token for 127.0.0.1
    token = mobile_access.generate_token("127.0.0.1")

    # Upstream mock transport returning dummy bytes with range support
    def mock_transport_handler(request: httpx.Request):
        range_header = request.headers.get("range", "")
        body = b"0123456789"
        if range_header:
            return httpx.Response(
                206,
                headers={
                    "Content-Range": "bytes 0-4/10",
                    "Content-Length": "5",
                    "Accept-Ranges": "bytes",
                    "Content-Type": "video/mp4",
                },
                stream=httpx.ByteStream(b"01234"),
            )
        return httpx.Response(
            200,
            headers={
                "Content-Length": "10",
                "Accept-Ranges": "bytes",
                "Content-Type": "video/mp4",
            },
            stream=httpx.ByteStream(body),
        )

    real_client = httpx.AsyncClient
    def client_factory(*args, **kw):
        if "transport" in kw:
            return real_client(*args, **kw)
        return real_client(*args, transport=httpx.MockTransport(mock_transport_handler), **kw)
    return app, token, client_factory


@pytest.mark.asyncio
async def test_router_mobile_play_direct_url_and_headers(mock_remote_setup):
    """POST /api/remote/mobile creates direct session with /media url and checks GET/HEAD headers."""
    app, token, client_factory = mock_remote_setup

    file_info = {"id": 1, "name": "movie.mp4", "path": "movie.mp4", "length": 1000}
    playback_mock = MagicMock()
    playback_mock.select_torrent_file = AsyncMock(return_value={"file": file_info})
    playback_mock.active_states = {}

    repo_mock = MagicMock()
    repo_mock.get_previous_progress.return_value = None
    repo_mock.logical_progress.return_value = None

    history_mock = MagicMock()

    ts_mock = MagicMock()
    ts_mock.require_ram_cache = AsyncMock()
    ts_mock.stream_url = MagicMock(return_value="http://127.0.0.1:8090/stream")
    ts_mock.torrent_video_files = AsyncMock(return_value=[file_info])

    app.dependency_overrides[deps.get_playback_service] = lambda: playback_mock
    app.dependency_overrides[deps.get_playback_repo] = lambda: repo_mock
    app.dependency_overrides[deps.get_history_repo] = lambda: history_mock
    app.dependency_overrides[deps.get_magnet_service] = lambda: AsyncMock()
    app.dependency_overrides[deps.get_torrserver_client] = lambda: ts_mock
    app.dependency_overrides[deps.get_torrserver_url] = lambda: "http://127.0.0.1:8090"

    base_url = "http://127.0.0.1:8000"
    with patch("backend.api.routers.remote.probe", new=AsyncMock(return_value={"mode": "direct", "duration": 120.0})), \
         patch("backend.services.mobile.httpx.AsyncClient", side_effect=client_factory):

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 12345)), base_url=base_url) as client:
            client.headers["X-Remote-Token"] = token

            # 1. Launch mobile playback
            res = await client.post(f"{base_url}/api/remote/mobile", json={"hash": "a" * 40, "file_id": 1})
            assert res.status_code == 200, f"Error {res.status_code}: {res.text}"
            data = res.json()
            assert data["mode"] == "direct"
            assert "/media" in data["url"]
            stream_token = data["token"]

            # 2. GET /media returns Content-Type: video/mp4 and Accept-Ranges: bytes
            media_res = await client.get(f"{base_url}/api/remote/mobile/{stream_token}/media", headers={"Range": "bytes=0-4"})
            assert media_res.status_code == 206
            assert media_res.headers["Content-Type"] == "video/mp4"
            assert media_res.headers["Accept-Ranges"] == "bytes"

            # 3. HEAD /media returns the same headers
            head_res = await client.head(f"{base_url}/api/remote/mobile/{stream_token}/media")
            assert head_res.status_code in (200, 206)
            assert head_res.headers["Content-Type"] == "video/mp4"
            assert head_res.headers["Accept-Ranges"] == "bytes"


@pytest.mark.asyncio
async def test_router_mobile_play_remux_url_and_headers(mock_remote_setup):
    """POST /api/remote/mobile creates remux session with /remux url and checks GET/HEAD headers."""
    app, token, client_factory = mock_remote_setup

    file_info = {"id": 2, "name": "movie.mkv", "path": "movie.mkv", "length": 5000}
    playback_mock = MagicMock()
    playback_mock.select_torrent_file = AsyncMock(return_value={"file": file_info})
    playback_mock.active_states = {}

    repo_mock = MagicMock()
    repo_mock.get_previous_progress.return_value = None
    repo_mock.logical_progress.return_value = None

    ts_mock = MagicMock()
    ts_mock.require_ram_cache = AsyncMock()
    ts_mock.stream_url = MagicMock(return_value="http://127.0.0.1:8090/stream.mkv")
    ts_mock.torrent_video_files = AsyncMock(return_value=[file_info])

    app.dependency_overrides[deps.get_playback_service] = lambda: playback_mock
    app.dependency_overrides[deps.get_playback_repo] = lambda: repo_mock
    app.dependency_overrides[deps.get_history_repo] = lambda: MagicMock()
    app.dependency_overrides[deps.get_magnet_service] = lambda: AsyncMock()
    app.dependency_overrides[deps.get_torrserver_client] = lambda: ts_mock
    app.dependency_overrides[deps.get_torrserver_url] = lambda: "http://127.0.0.1:8090"

    base_url = "http://127.0.0.1:8000"
    with patch("backend.api.routers.remote.probe", new=AsyncMock(return_value={"mode": "remux", "duration": 3600.0})), \
         patch("backend.services.mobile.httpx.AsyncClient", side_effect=client_factory):

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 12345)), base_url=base_url) as client:
            client.headers["X-Remote-Token"] = token

            # 1. Launch mobile playback
            res = await client.post(f"{base_url}/api/remote/mobile", json={"hash": "b" * 40, "file_id": 2})
            assert res.status_code == 200
            data = res.json()
            assert data["mode"] == "remux"
            assert "/hls/playlist.m3u8" in data["url"]
            stream_token = data["token"]

            # 2. GET /remux returns Content-Type: video/mp4 and Accept-Ranges: bytes
            remux_res = await client.get(f"{base_url}/api/remote/mobile/{stream_token}/remux", headers={"Range": "bytes=0-4"})
            assert remux_res.status_code == 206
            assert remux_res.headers["Content-Type"] == "video/mp4"
            assert remux_res.headers["Accept-Ranges"] == "bytes"

            # 3. HEAD /remux returns the same headers
            head_res = await client.head(f"{base_url}/api/remote/mobile/{stream_token}/remux")
            assert head_res.status_code in (200, 206)
            assert head_res.headers["Content-Type"] == "video/mp4"
            assert head_res.headers["Accept-Ranges"] == "bytes"


@pytest.mark.asyncio
async def test_router_mobile_play_transcode_url(mock_remote_setup):
    """POST /api/remote/mobile creates transcode session with /hls/playlist.m3u8 url."""
    app, token, _ = mock_remote_setup

    file_info = {"id": 3, "name": "series.mkv", "path": "series.mkv", "length": 8000}
    playback_mock = MagicMock()
    playback_mock.select_torrent_file = AsyncMock(return_value={"file": file_info})
    playback_mock.active_states = {}

    repo_mock = MagicMock()
    repo_mock.get_previous_progress.return_value = None
    repo_mock.logical_progress.return_value = None

    ts_mock = MagicMock()
    ts_mock.require_ram_cache = AsyncMock()
    ts_mock.stream_url = MagicMock(return_value="http://127.0.0.1:8090/series.mkv")
    ts_mock.torrent_video_files = AsyncMock(return_value=[file_info])

    app.dependency_overrides[deps.get_playback_service] = lambda: playback_mock
    app.dependency_overrides[deps.get_playback_repo] = lambda: repo_mock
    app.dependency_overrides[deps.get_history_repo] = lambda: MagicMock()
    app.dependency_overrides[deps.get_magnet_service] = lambda: AsyncMock()
    app.dependency_overrides[deps.get_torrserver_client] = lambda: ts_mock
    app.dependency_overrides[deps.get_torrserver_url] = lambda: "http://127.0.0.1:8090"

    base_url = "http://127.0.0.1:8000"
    with patch("backend.api.routers.remote.probe", new=AsyncMock(return_value={"mode": "transcode", "duration": 1800.0})):

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 12345)), base_url=base_url) as client:
            client.headers["X-Remote-Token"] = token

            res = await client.post(f"{base_url}/api/remote/mobile", json={"hash": "c" * 40, "file_id": 3})
            assert res.status_code == 200
            data = res.json()
            assert data["mode"] == "transcode"
            assert "/hls/playlist.m3u8" in data["url"]

            # HLS Playlist response headers
            stream_token = data["token"]
            pl_res = await client.get(f"{base_url}/api/remote/mobile/{stream_token}/hls/playlist.m3u8")
            assert pl_res.status_code == 200
            assert pl_res.headers["Content-Type"] == "application/vnd.apple.mpegurl"
            assert pl_res.headers["Accept-Ranges"] == "bytes"
