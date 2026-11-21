"""Tests for Pydantic schemas validation and error handling / path sanitization."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.api.deps import (
    map_exception_to_http,
    register_exception_handlers,
    safe_execute,
    sanitize_error_message,
)
from backend.api.schemas.player import (
    MagnetRequest,
    PlayerCommandRequest,
    PlayRequest,
    SeekRequest,
    SetVolumeRequest,
    SubtitleSearch,
)
from backend.api.schemas.remote import (
    MobilePlayRequest,
    MobileProgress,
    PairRequest,
    RemotePlayRequest,
    RemoteSeekRequest,
    RemoteVolumeRequest,
)
from backend.exceptions import (
    AppException,
    ExternalServiceError,
    NotFoundError,
)

# ─── 1. Player Pydantic DTO Validation ───


def test_play_request_valid_and_conversion():
    req = PlayRequest(
        hash="4b92b6a7b7a1234567890abcdef1234567890abc",
        file_id=0,
        file_name="BigBuckBunny.mkv",
        start_time=120,
        audio_track=1,
        subtitle_track=2,
    )
    assert req.hash == "4b92b6a7b7a1234567890abcdef1234567890abc"
    assert req.file_id == 0
    assert req.file_name == "BigBuckBunny.mkv"
    cmd = req.to_command()
    assert cmd.hash == req.hash
    assert cmd.file_id == 0
    assert cmd.start_time == 120
    assert cmd.audio_track == 1
    assert cmd.subtitle_track == 2


def test_play_request_invalid_params():
    # Empty hash
    with pytest.raises(ValidationError):
        PlayRequest(hash="", file_id=0, file_name="Test.mkv")

    # Negative file_id
    with pytest.raises(ValidationError):
        PlayRequest(hash="abc", file_id=-1, file_name="Test.mkv")

    # Empty file_name
    with pytest.raises(ValidationError):
        PlayRequest(hash="abc", file_id=0, file_name="")

    # Negative start_time
    with pytest.raises(ValidationError):
        PlayRequest(hash="abc", file_id=0, file_name="Test.mkv", start_time=-10)


def test_seek_request_validation():
    # Valid relative seek
    s1 = SeekRequest(seconds=15.0, mode="relative")
    assert s1.to_command() == ["seek", 15.0, "relative"]

    # Valid absolute+exact seek
    s2 = SeekRequest(seconds=350.5, mode="absolute+exact")
    assert s2.to_command() == ["seek", 350.5, "absolute+exact"]

    # Default mode is relative
    s3 = SeekRequest(seconds=-10.0)
    assert s3.mode == "relative"
    assert s3.to_command() == ["seek", -10.0, "relative"]

    # Invalid mode pattern
    with pytest.raises(ValidationError):
        SeekRequest(seconds=10.0, mode="arbitrary_mode")

    # Out of range seconds
    with pytest.raises(ValidationError):
        SeekRequest(seconds=999999.0)


def test_set_volume_request_validation():
    # Valid volumes
    v0 = SetVolumeRequest(volume=0)
    assert v0.volume == 0
    assert v0.to_command() == ["set_property", "volume", 0]

    v100 = SetVolumeRequest(volume=100)
    assert v100.volume == 100
    assert v100.to_command() == ["set_property", "volume", 100]

    v50 = SetVolumeRequest(volume=50)
    assert v50.to_command() == ["set_property", "volume", 50]

    # Negative volume
    with pytest.raises(ValidationError):
        SetVolumeRequest(volume=-1)

    # Volume > 100
    with pytest.raises(ValidationError):
        SetVolumeRequest(volume=101)


def test_player_command_request_validation():
    # Valid scalar list
    cmd = PlayerCommandRequest(command=["set_property", "pause", True])
    assert cmd.command == ["set_property", "pause", True]

    # Empty command list
    with pytest.raises(ValidationError):
        PlayerCommandRequest(command=[])

    # First element not string
    with pytest.raises(ValidationError):
        PlayerCommandRequest(command=[123, "arg"])

    # Non-scalar item (e.g. dict or list in command)
    with pytest.raises(ValidationError):
        PlayerCommandRequest(command=["seek", {"target": 10}])


def test_subtitle_and_magnet_validation():
    # Valid subtitle search
    sub = SubtitleSearch(hash="abc", file_id=0, title="Movie", language="RU,EN")
    assert sub.language == "RU,EN"

    # Invalid subtitle search language
    with pytest.raises(ValidationError):
        SubtitleSearch(hash="abc", file_id=0, language="FR")

    # Valid magnet request
    mag = MagnetRequest(magnet="magnet:?xt=urn:btih:abcdef1234567890", title="Test")
    assert mag.title == "Test"

    # Too short magnet string
    with pytest.raises(ValidationError):
        MagnetRequest(magnet="short")


# ─── 2. Remote Pydantic DTO Validation ───


def test_pair_request_validation():
    # Valid code
    p = PairRequest(code="1234")
    assert p.code == "1234"

    # Empty code
    with pytest.raises(ValidationError):
        PairRequest(code="")

    # Too long code
    with pytest.raises(ValidationError):
        PairRequest(code="x" * 33)


def test_remote_play_and_mobile_play_validation():
    # Valid remote play
    rp = RemotePlayRequest(hash="abc1234", title="Film", fullscreen=True)
    assert rp.hash == "abc1234"
    assert rp.fullscreen is True

    # Valid mobile play with season/episode
    mp = MobilePlayRequest(hash="abc1234", season=1, episode=5, absolute=5)
    assert mp.season == 1
    assert mp.episode == 5

    # Negative season
    with pytest.raises(ValidationError):
        MobilePlayRequest(season=-1)

    # Negative episode
    with pytest.raises(ValidationError):
        MobilePlayRequest(episode=-1)


def test_mobile_progress_validation():
    # Valid progress
    prog = MobileProgress(sequence=1, position=120.5, duration=3600.0, close=False)
    assert prog.sequence == 1
    assert prog.position == 120.5

    # Negative sequence
    with pytest.raises(ValidationError):
        MobileProgress(sequence=-1, position=0.0, duration=100.0)

    # Negative position
    with pytest.raises(ValidationError):
        MobileProgress(sequence=1, position=-10.0, duration=100.0)

    # Negative duration
    with pytest.raises(ValidationError):
        MobileProgress(sequence=1, position=10.0, duration=-5.0)

    # Position exceeding 1 week (604800s)
    with pytest.raises(ValidationError):
        MobileProgress(sequence=1, position=700000.0, duration=100.0)


def test_remote_seek_and_volume_validation():
    # Remote seek
    r_seek = RemoteSeekRequest(seconds=30.0, mode="relative")
    assert r_seek.seconds == 30.0
    with pytest.raises(ValidationError):
        RemoteSeekRequest(seconds=30.0, mode="invalid")

    # Remote volume
    r_vol = RemoteVolumeRequest(volume=80)
    assert r_vol.volume == 80
    with pytest.raises(ValidationError):
        RemoteVolumeRequest(volume=150)


# ─── 3. Path Sanitization & Error Transformation ───


def test_sanitize_error_message_removes_windows_paths():
    raw = r"Failed to open C:\Users\stark\Desktop\pirate-cinema-2\video.mkv: file not found"
    sanitized = sanitize_error_message(raw)
    assert "C:\\Users" not in sanitized
    assert "<path>" in sanitized
    assert ": file not found" in sanitized


def test_sanitize_error_message_removes_unix_paths():
    raw = "Cannot load subtitle from /home/ubuntu/data/subtitles/track.srt"
    sanitized = sanitize_error_message(raw)
    assert "/home/ubuntu" not in sanitized
    assert "<path>" in sanitized


def test_sanitize_error_message_removes_unc_paths():
    raw = r"Network share \\192.168.1.100\media\movie.mp4 is unreachable"
    sanitized = sanitize_error_message(raw)
    assert r"\\192.168.1.100" not in sanitized
    assert "<path>" in sanitized


def test_sanitize_error_message_preserves_urls_and_endpoints():
    url_msg = "TorrServer at http://127.0.0.1:8090/stream is unavailable"
    sanitized = sanitize_error_message(url_msg)
    assert "http://127.0.0.1:8090/stream" in sanitized

    api_msg = "Endpoint /api/player/play rejected the request"
    sanitized_api = sanitize_error_message(api_msg)
    assert "/api/player/play" in sanitized_api


def test_sanitize_error_message_strips_stack_traces():
    msg_with_trace = (
        "Database locked\nTraceback (most recent call last):\n"
        '  File "C:\\app\\repo.py", line 42, in get\n'
        "    raise sqlite3.OperationalError('locked')"
    )
    sanitized = sanitize_error_message(msg_with_trace)
    assert "Traceback" not in sanitized
    assert "line 42" not in sanitized
    assert "Database locked" in sanitized


def test_map_exception_to_http():
    # 1. AppException
    app_exc = AppException("Failed to load torrent C:\\secret\\file.torrent", status_code=400)
    code, detail = map_exception_to_http(app_exc)
    assert code == 400
    assert "C:\\secret" not in detail
    assert "<path>" in detail

    # 2. NotFoundError
    not_found = NotFoundError("Item not found in /var/db/library.sqlite")
    code, detail = map_exception_to_http(not_found)
    assert code == 404
    assert "/var/db" not in detail

    # 3. ExternalServiceError
    ext_err = ExternalServiceError("TorrServer connection timed out")
    code, detail = map_exception_to_http(ext_err)
    assert code == 502
    assert detail == "TorrServer connection timed out"

    # 4. FileNotFoundError
    fnf = FileNotFoundError(2, "No such file", "C:\\data\\test.mkv")
    code, detail = map_exception_to_http(fnf)
    assert code == 404
    assert "C:\\data" not in detail

    # 5. PermissionError
    perm = PermissionError(13, "Permission denied", "/etc/config.json")
    code, detail = map_exception_to_http(perm)
    assert code == 403
    assert "/etc" not in detail

    # 6. ValueError
    val_err = ValueError("Invalid parameter value for quality")
    code, detail = map_exception_to_http(val_err)
    assert code == 400
    assert detail == "Invalid parameter value for quality"

    # 7. Unhandled internal error
    unhandled = RuntimeError("Unexpected internal engine fault in C:\\runtime\\engine.dll")
    code, detail = map_exception_to_http(unhandled)
    assert code == 500
    assert "engine.dll" not in detail
    assert detail == "Internal server error"


def test_safe_execute_helper():
    # Successful execution
    res = safe_execute(lambda x, y: x + y, 3, 4)
    assert res == 7

    # Exception caught and raised as HTTPException without paths
    with pytest.raises(Exception) as exc_info:
        safe_execute(
            lambda: (_ for _ in ()).throw(AppException("Error in C:\\db\\test.db", status_code=400))
        )
    assert exc_info.value.status_code == 400
    assert "C:\\db" not in exc_info.value.detail


# ─── 4. FastAPI Integration with Unified Exception Handlers ───


def test_fastapi_unified_exception_handling():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/test/domain-error")
    def trigger_domain_error():
        raise AppException("Cannot read media at C:\\sensitive\\vault\\movie.mkv", status_code=400)

    @app.get("/test/not-found-error")
    def trigger_not_found():
        raise NotFoundError("Playlist /var/data/playlists/fav.m3u not found")

    @app.get("/test/file-not-found")
    def trigger_fnf():
        raise FileNotFoundError(2, "No such file", "C:\\Windows\\system32\\mpv.exe")

    @app.get("/test/internal-crash")
    def trigger_crash():
        raise RuntimeError("Stack dump in C:\\app\\kernel.py: line 99: crash")

    @app.post("/test/validate")
    def validate_body(req: SeekRequest):
        return {"ok": True, "cmd": req.to_command()}

    client = TestClient(app, raise_server_exceptions=False)

    # 1. Domain error sanitized
    resp = client.get("/test/domain-error")
    assert resp.status_code == 400
    assert "C:\\sensitive" not in resp.json()["detail"]
    assert "<path>" in resp.json()["detail"]

    # 2. Not found sanitized
    resp = client.get("/test/not-found-error")
    assert resp.status_code == 404
    assert "/var/data" not in resp.json()["detail"]

    # 3. FileNotFoundError sanitized
    resp = client.get("/test/file-not-found")
    assert resp.status_code == 404
    assert "system32" not in resp.json()["detail"]

    # 4. Internal crash returns safe 500 without stack trace
    resp = client.get("/test/internal-crash")
    assert resp.status_code == 500
    assert "kernel.py" not in resp.json()["detail"]
    assert "line 99" not in resp.json()["detail"]
    assert resp.json()["detail"] == "Internal server error"

    # 5. Invalid body returns 422
    resp = client.post("/test/validate", json={"seconds": 10.0, "mode": "unsupported_mode"})
    assert resp.status_code == 422
