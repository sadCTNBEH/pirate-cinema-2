import io
import json
import os
import shutil
import subprocess
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from backend.infrastructure.mpv.controller import MPVController


@pytest.mark.skipif(not shutil.which("mpv") or not shutil.which("ffmpeg"), reason="MPV and FFmpeg required")
def test_standalone_mpv_http_headers_for_hls_and_dash(tmp_path, monkeypatch):
    from backend.core.settings.config import config

    monkeypatch.setattr("backend.infrastructure.mpv.controller.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "MPV_ARGS", [arg for arg in config.MPV_ARGS if arg != "--fs"] +
                        ["--ao=null", "--vo=null"])
    monkeypatch.setenv("CINEMA_MPV_OSC", "legacy")
    headers = {
        "Referer": "https://player.example/",
        "Origin": "https://player.example",
        "User-Agent": "Pirate Cinema, playback test",
        "Cookie": "session=abc,def",
        "Authorization": "Bearer stream-test",
    }
    manifests = {"hls": "main.m3u8", "dash": "main.mpd"}
    for container, name in manifests.items():
        folder = tmp_path / container
        folder.mkdir()
        subprocess.run([
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=20",
            "-t", "2", "-threads", "1", "-c:v", "libx264", "-g", "20", "-f", container, name,
        ], cwd=folder, check=True, timeout=15)

    rejected = []
    requested_segments = set()

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path)
            expected = dict(headers)
            if path.path.startswith("/dash/"):
                expected["Cookie"] = "session=replacement"
            if (any(self.headers.get(key) != value for key, value in expected.items())
                    or (path.path.endswith((".m3u8", ".mpd")) and path.query != "auth=a%2Bb")):
                rejected.append(path.path)
                self.send_error(403)
                return
            if path.path.endswith((".ts", ".m4s")):
                requested_segments.add(path.path.split("/")[1])
            super().do_GET()

        def log_message(self, *_args):
            pass

    controller = MPVController()
    played = {container: threading.Event() for container in manifests}

    def record_playback(name, value):
        if name == "time-pos" and isinstance(value, (int, float)) and value > 0.1:
            container = urlsplit(controller.media_url).path.split("/")[1]
            event = played.get(container) if container in requested_segments else None
            if event:
                event.set()

    controller.on_progress = record_playback
    with ThreadingHTTPServer(("127.0.0.1", 0), lambda *args: Handler(*args, directory=tmp_path)) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            controller.configure_network("", headers)
            controller.launch(shutil.which("mpv"), f"{base}/hls/main.m3u8?auth=a%2Bb", "HLS")
            assert played["hls"].wait(10), (rejected, (tmp_path / "mpv_debug.log").read_text()[-2000:])

            controller.configure_network("", {**headers, "Cookie": "session=replacement"})
            controller.load_file(f"{base}/dash/main.mpd?auth=a%2Bb", "DASH")
            assert played["dash"].wait(10), (rejected, (tmp_path / "mpv_debug.log").read_text()[-2000:])
            assert not rejected
        finally:
            controller.stop()
            server.shutdown()
            worker.join()


def test_mpv_reader_loop_handles_auto_and_no_properties(mpv_ipc_stream):
    controller = MPVController()
    controller.is_running = True

    events_stream = mpv_ipc_stream(
        b'{"event":"property-change","id":3,"name":"aid","data":"auto"}\n'
        b'{"event":"property-change","id":4,"name":"sid","data":"no"}\n'
        b'{"event":"property-change","id":1,"name":"time-pos","data":15.5}\n'
        b'{"event":"property-change","id":2,"name":"duration","data":120.0}\n'
        b'{"event":"end-file","reason":"eof"}\n'
    )
    controller.pipe = events_stream

    progress_calls = []
    end_calls = []

    controller.on_progress = lambda name, val: progress_calls.append((name, val))
    controller.on_end = lambda reason: end_calls.append(reason)

    controller._reader_loop()

    assert ("aid", "auto") in progress_calls
    assert ("sid", "no") in progress_calls
    assert ("time-pos", 15.5) in progress_calls
    assert ("duration", 120.0) in progress_calls
    assert ("flush", True) in progress_calls
    # EOF finishes the file, not the IPC session; a subsequent broken pipe is distinct.
    assert end_calls == ["eof", "ipc_lost"]


def test_mpv_reader_loop_resilient_to_callback_exception(mpv_ipc_stream):
    controller = MPVController()
    controller.is_running = True

    events_stream = mpv_ipc_stream(
        b'{"event":"property-change","id":3,"name":"aid","data":"auto"}\n'
        b'{"event":"property-change","id":1,"name":"time-pos","data":25.0}\n'
    )
    controller.pipe = events_stream

    received = []

    def flaky_progress(name, val):
        if name == "aid":
            raise ValueError("simulated callback error")
        received.append((name, val))

    controller.on_progress = flaky_progress
    controller._reader_loop()

    # Loop did not terminate on aid error; continued to process time-pos
    assert ("time-pos", 25.0) in received


@pytest.mark.parametrize("has_index", [False, True])
def test_mpv_load_file_commands(has_index, mpv_ipc_stream):
    controller = MPVController()
    args = [{"name": name} for name in ("url", "flags", "options")]
    if has_index:
        args.insert(2, {"name": "index"})
    signature = {"request_id": 8104, "error": "success", "data": [{"name": "loadfile", "args": args}]}
    controller.is_running = True
    controller.pipe = mpv_ipc_stream((json.dumps(signature) + "\n").encode())
    controller._reader_loop()
    index_argument = [-1] if has_index else []
    sent_commands = []
    controller.send_command = lambda cmd: sent_commands.append(cmd)

    # 1. Default parameters (start=0, audio=0, sub=0)
    controller.load_file("http://test.url/video.mkv", "Episode 1")
    assert ["set_property", "start", "none"] in sent_commands
    assert ["set_property", "force-media-title", "Episode 1"] in sent_commands
    assert [
        "loadfile",
        "http://test.url/video.mkv",
        "replace",
        *index_argument,
        "pause=no,start=0,sub-delay=0.0,audio-delay=0.0",
    ] in sent_commands
    assert ["set_property", "pause", False] in sent_commands

    # 2. Custom tracks and start timecode
    sent_commands.clear()
    controller.load_file(
        "http://test.url/ep2.mkv",
        "Episode 2",
        start_time=150,
        audio_track=2,
        subtitle_track=3,
    )
    assert ["set_property", "start", "none"] in sent_commands
    assert ["set_property", "force-media-title", "Episode 2"] in sent_commands
    assert ["set_property", "aid", 2] in sent_commands
    assert ["set_property", "sid", 3] in sent_commands
    assert [
        "loadfile",
        "http://test.url/ep2.mkv",
        "replace",
        *index_argument,
        "pause=no,start=150,sub-delay=0.0,audio-delay=0.0,aid=2,sid=3",
    ] in sent_commands
    assert ["set_property", "pause", False] in sent_commands


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("wid", [123456, None])
def test_mpv_launch_with_wid(monkeypatch, legacy, wid, mpv_ipc_stream):
    if legacy:
        monkeypatch.setenv("CINEMA_MPV_OSC", "legacy")
    else:
        monkeypatch.delenv("CINEMA_MPV_OSC", raising=False)
    controller = MPVController()
    captured_args = []

    def mock_popen(args, **kwargs):
        captured_args.extend(args)

        class DummyProcess:
            pid = 9999
            stdin = io.BytesIO()
            stdout = io.BytesIO()
            stderr = io.BytesIO()

            def poll(self):
                return None

            def terminate(self):
                pass

            def wait(self, timeout=None):
                return 0

        return DummyProcess()

    monkeypatch.setattr("subprocess.Popen", mock_popen)
    monkeypatch.setattr("backend.infrastructure.mpv.controller.config.MPV_ARGS", ["--fs", "--idle=yes"])

    import builtins
    orig_open = builtins.open

    def mock_open(file, *args, **kwargs):
        if str(file) == controller.pipe_name:
            return io.BytesIO()
        return orig_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", mock_open)
    monkeypatch.setattr(controller, "_open_pipe", lambda p: mpv_ipc_stream())
    monkeypatch.setattr(controller, "send_command", lambda cmd: None)
    monkeypatch.setattr(controller, "load_file", lambda *a, **kw: None)
    monkeypatch.setattr(controller, "_verify_cache", lambda: None)
    monkeypatch.setattr(controller, "_detect_loadfile_signature", lambda: None)

    controller.launch("mpv", "http://test.url/video.mkv", "Test Title", wid=wid)

    if wid is not None:
        assert "--wid=123456" in captured_args
        assert ("--osc=yes" if legacy else "--osc=no") in captured_args
        assert ("--input-doubleclick-time=0" in captured_args) is not legacy
        assert ("--cursor-autohide=1500" if legacy else "--cursor-autohide=no") in captured_args
        assert any(arg.startswith("--script=") and arg.endswith("cinema.lua") for arg in captured_args) is not legacy
        assert "--input-default-bindings=yes" in captured_args
        assert ("--input-vo-keyboard=no" if os.name == "nt" else "--input-vo-keyboard=yes") in captured_args
        assert ("--input-builtin-dragging=no" in captured_args) is (os.name == "nt")
        assert "--window-dragging=no" in captured_args
        assert "--input-cursor=yes" in captured_args
        assert "--keepaspect=yes" in captured_args
        assert "--fs" not in captured_args
        if os.name == "nt":
            assert "--gpu-api=d3d11" in captured_args
            assert "--gpu-context=d3d11" in captured_args
            assert "--gpu-api=opengl" not in captured_args
            assert "--gpu-context=win" not in captured_args
            assert "--hwdec=auto-safe" in captured_args
    else:
        assert "--fs" in captured_args
        assert not any(arg.startswith("--wid=") for arg in captured_args)
        if os.name == "nt":
            assert "--gpu-api=opengl" in captured_args
            assert "--gpu-context=win" in captured_args
            assert "--hwdec=auto-safe" in captured_args
    controller.is_running = False


def test_mpv_reader_loop_handles_fullscreen_property(mpv_ipc_stream):
    controller = MPVController()
    controller.is_running = True

    events_stream = mpv_ipc_stream(
        b'{"event":"property-change","id":6,"name":"fullscreen","data":true}\n'
        b'{"event":"property-change","id":6,"name":"fullscreen","data":false}\n'
    )
    controller.pipe = events_stream

    progress_calls = []
    controller.on_progress = lambda name, val: progress_calls.append((name, val))

    controller._reader_loop()

    assert ("fullscreen", True) in progress_calls
    assert ("fullscreen", False) in progress_calls


def test_mpv_reader_loop_handles_track_list(mpv_ipc_stream):
    controller = MPVController()
    controller.is_running = True

    events_stream = mpv_ipc_stream(
        b'{"event":"property-change","id":10,"name":"track-list","data":[{"id":1,"type":"audio","lang":"rus"}]}\n'
    )
    controller.pipe = events_stream

    progress_calls = []
    controller.on_progress = lambda name, val: progress_calls.append((name, val))

    controller._reader_loop()

    assert ("track-list", [{"id": 1, "type": "audio", "lang": "rus"}]) in progress_calls


def test_smoke_test_mpv_preserves_cache_policy_args(monkeypatch):
    import run
    from backend.core.settings import config

    launched = []

    class MockController:
        def launch(self, binary, url, title):
            launched.append((binary, url, title, list(config.MPV_ARGS)))
            self.on_progress("time-pos", 0.5)

        def stop(self):
            pass

    monkeypatch.setattr(run.sys, "argv", ["run.py", "--smoke-test-mpv"])
    monkeypatch.setattr("backend.infrastructure.mpv.controller.MPVController", MockController)
    monkeypatch.setattr("backend.core.settings.resolve_mpv_binary", lambda *a: "mock_mpv")

    assert run.main() == 0
    assert len(launched) == 1
    args = launched[0][3]
    assert "--vo=null" in args
    assert "--ao=null" in args
    assert "--cache=yes" in args
    assert "--cache-on-disk=no" in args
    assert "--demuxer-max-bytes=128MiB" in args
    assert "--demuxer-max-back-bytes=32MiB" in args


def test_mpv_startup_arguments_optimization(monkeypatch, mpv_ipc_stream):
    """Verify MPV launch includes hwdec=auto-safe, optimal demuxer sizes, and fast-start cache options."""
    controller = MPVController()
    captured_args = []

    class DummyProcess:
        pid = 1234
        def poll(self):
            return None
        def terminate(self):
            pass
        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr("subprocess.Popen", lambda args, **kw: (captured_args.extend(args), DummyProcess())[1])
    monkeypatch.setattr(controller, "_open_pipe", lambda p: mpv_ipc_stream())
    monkeypatch.setattr(controller, "send_command", lambda cmd: None)
    monkeypatch.setattr(controller, "load_file", lambda *a, **kw: None)
    monkeypatch.setattr(controller, "_verify_cache", lambda: None)
    monkeypatch.setattr(controller, "_detect_loadfile_signature", lambda: None)

    controller.launch("mpv", "http://test.url/video.mkv", "Startup Test", wid=999)

    # 1. Hardware decoding auto-selection
    assert "--hwdec=auto-safe" in captured_args

    # 2. Demuxer and readahead optimization
    assert "--demuxer-max-bytes=128MiB" in captured_args
    assert "--demuxer-readahead-secs=20" in captured_args
    assert "--demuxer-max-back-bytes=32MiB" in captured_args

    # 3. Cache and first-frame latency options
    assert "--cache=yes" in captured_args
    assert "--cache-on-disk=no" in captured_args
    assert "--cache-pause-initial=no" in captured_args
    assert "--cache-pause-wait=1" in captured_args

    controller.is_running = False


def test_mpv_launch_hwdec_fallback_to_software(monkeypatch, mpv_ipc_stream):
    """Verify fallback from HWDEC to software decoding (--hwdec=no) if initial launch crashes."""
    controller = MPVController()
    attempts = []

    class DummyProcess:
        pid = 4321
        def poll(self):
            return None
        def terminate(self):
            pass
        def wait(self, timeout=None):
            return 0

    def mock_spawn_and_connect(args, log_path):
        attempts.append(list(args))
        # First attempt with hwdec=auto-safe fails (simulating driver crash on startup)
        if any(a == "--hwdec=auto-safe" for a in args):
            raise RuntimeError("Failed to connect to MPV IPC: driver crashed")
        return mpv_ipc_stream()

    monkeypatch.setattr(controller, "_spawn_and_connect", mock_spawn_and_connect)
    monkeypatch.setattr(controller, "_reader_loop", lambda: None)
    monkeypatch.setattr(controller, "send_command", lambda cmd: None)
    monkeypatch.setattr(controller, "load_file", lambda *a, **kw: None)
    monkeypatch.setattr(controller, "_verify_cache", lambda: None)
    monkeypatch.setattr(controller, "_detect_loadfile_signature", lambda: None)

    controller.launch("mpv", "http://test.url/video.mkv", "Fallback Test")

    assert len(attempts) == 2
    # First attempt had auto-safe
    assert any("--hwdec=auto-safe" in arg for arg in attempts[0])
    # Second attempt fell back to software decoding
    assert any("--hwdec=no" in arg for arg in attempts[1])
    assert controller.is_running is True
    assert controller._hwdec_mode == "no"
    assert controller._hwdec_fallback_done is True
    controller.is_running = False


def test_mpv_runtime_hwdec_fallback_on_error(mpv_ipc_stream):
    """Verify that end-file error during playback triggers runtime fallback to software decoding via load_file."""
    controller = MPVController()
    controller.is_running = True
    controller._hwdec_mode = "auto-safe"
    controller._hwdec_fallback_done = False
    controller.media_url = "http://test.url/hevc10bit.mkv"
    controller._current_title = "HEVC 10-bit Video"
    controller._properties["time-pos"] = 45.0

    sent_commands = []
    loaded_files = []
    controller.send_command = lambda cmd: sent_commands.append(cmd)
    controller.load_file = lambda url, title, start_time, **kw: loaded_files.append((url, title, start_time))

    events_stream = mpv_ipc_stream(
        b'{"event":"end-file","reason":"error"}\n'
    )
    controller.pipe = events_stream

    end_reasons = []
    controller.on_end = lambda r: end_reasons.append(r)

    controller._reader_loop()

    # Must send set_property hwdec no
    assert ["set_property", "hwdec", "no"] in sent_commands
    # Must reload the file via load_file at the current time position
    assert len(loaded_files) == 1
    assert loaded_files[0] == ("http://test.url/hevc10bit.mkv", "HEVC 10-bit Video", 45)
    # Player must NOT have reported 'error' to on_end (fallback intercepted it)
    assert "error" not in end_reasons
    assert controller._hwdec_mode == "no"
    assert controller._hwdec_fallback_done is True


def test_mpv_runtime_hwdec_fallback_on_log_message(mpv_ipc_stream):
    """Verify that HWDEC failure log message triggers runtime fallback to software decoding."""
    controller = MPVController()
    controller.is_running = True
    controller._hwdec_mode = "auto-safe"
    controller._hwdec_fallback_done = False
    controller.media_url = "http://test.url/av1_movie.mkv"
    controller._current_title = "AV1 Movie"
    controller._properties["time-pos"] = 12.0

    sent_commands = []
    loaded_files = []
    controller.send_command = lambda cmd: sent_commands.append(cmd)
    controller.load_file = lambda url, title, start_time, **kw: loaded_files.append((url, title, start_time))

    events_stream = mpv_ipc_stream(
        b'{"event":"log-message","prefix":"ffmpeg","level":"error","text":"Hardware decoding failed, falling back to software decoding."}\n'
    )
    controller.pipe = events_stream

    controller._reader_loop()

    assert ["set_property", "hwdec", "no"] in sent_commands
    assert len(loaded_files) == 1
    assert loaded_files[0] == ("http://test.url/av1_movie.mkv", "AV1 Movie", 12)
    assert controller._hwdec_mode == "no"


def test_mpv_avoid_recreating_process_when_running():
    """Verify controller.launch avoids process stop and recreation when already running with matching window."""
    controller = MPVController()
    controller.is_running = True
    controller._wid = 555

    class MockProcess:
        pid = 7777
        def poll(self):
            return None

    controller.process = MockProcess()
    stopped = []
    controller.stop = lambda: stopped.append(True)

    loaded = []
    controller.load_file = lambda url, title, start_time=0, **kw: loaded.append((url, title, start_time))

    # Calling start_file with matching wid=555 should NOT call stop(), but load_file()
    controller.start_file("http://test.url/next_ep.mkv", "Next Episode", start_time=15, wid=555)

    assert len(stopped) == 0
    assert len(loaded) == 1
    assert loaded[0] == ("http://test.url/next_ep.mkv", "Next Episode", 15)
    assert controller.process.pid == 7777


@pytest.mark.asyncio
async def test_mpv_playback_service_integration_args_and_loadfile_reuse(monkeypatch, mpv_ipc_stream):
    """Integration test: PlaybackService launches MPV with optimal args and reuses process via loadfile."""
    from unittest.mock import AsyncMock, MagicMock
    from backend.models.playback import PlayCommand
    from backend.repositories.playback import PlaybackRepository
    from backend.services.playback import PlaybackService

    captured_launch_args = []
    sent_ipc_commands = []

    class MockSubprocess:
        pid = 54321
        def poll(self):
            return None
        def terminate(self):
            pass
        def wait(self, timeout=None):
            return 0

    def mock_popen(args, **kw):
        captured_launch_args.append(list(args))
        return MockSubprocess()

    monkeypatch.setattr("subprocess.Popen", mock_popen)

    mock_db = MagicMock()
    repo = PlaybackRepository(mock_db)
    repo.get_previous_progress = MagicMock(return_value=None)
    repo.logical_progress = MagicMock(return_value=None)
    repo.file_choice = MagicMock(return_value=None)
    repo.file_intent = MagicMock(return_value=None)
    repo.get_sync = MagicMock(return_value=(0.0, 0.0))

    history = MagicMock()
    metadata = MagicMock()
    metadata.save_media_type = MagicMock()
    metadata.save_metadata_title = MagicMock()
    metadata.get_imdb_id = MagicMock(return_value=None)

    torrserver = MagicMock()
    torrserver.require_ram_cache = AsyncMock()
    torrserver.stream_url = MagicMock(side_effect=lambda url, h, fid, fname: f"http://ts/{h}/{fid}")
    torrserver.torrent_video_files = AsyncMock(return_value=[])

    controller_instances = []

    def real_controller_factory():
        c = MPVController()
        monkeypatch.setattr(c, "_open_pipe", lambda p: mpv_ipc_stream())
        monkeypatch.setattr(c, "_reader_loop", lambda: None)
        monkeypatch.setattr(c, "_verify_cache", lambda: None)
        monkeypatch.setattr(c, "_detect_loadfile_signature", lambda: None)

        orig_send = c.send_command
        def spy_send(cmd, *a, **k):
            sent_ipc_commands.append(list(cmd))
            return orig_send(cmd, *a, **k)

        monkeypatch.setattr(c, "send_command", spy_send)
        controller_instances.append(c)
        return c

    service = PlaybackService(
        playback_repo=repo,
        history_repo=history,
        metadata_repo=metadata,
        mpv_controller_factory=real_controller_factory,
        torrserver_client=torrserver,
        settings_provider=lambda: "http://localhost:8090",
    )

    # 1. First launch: process must be created with optimal MPV startup arguments
    cmd1 = PlayCommand(hash="torrent1", file_id=0, file_name="Video1.mkv", start_time=0)
    res1 = await service.launch(cmd1)
    assert res1 == "launched"
    assert len(controller_instances) == 1
    c1 = controller_instances[0]
    assert c1.is_running is True
    assert len(captured_launch_args) == 1
    args1 = captured_launch_args[0]

    # Verify launch arguments
    assert "--hwdec=auto-safe" in args1
    assert "--demuxer-max-bytes=128MiB" in args1
    assert "--demuxer-readahead-secs=20" in args1
    assert "--cache=yes" in args1
    assert "--cache-on-disk=no" in args1
    assert "--cache-pause-initial=no" in args1
    assert "--cache-pause-wait=1" in args1

    # 2. Second launch (switch to new video): process must NOT be recreated
    cmd2 = PlayCommand(hash="torrent2", file_id=1, file_name="Video2.mkv", start_time=30)
    res2 = await service.launch(cmd2)
    assert res2 == "launched"

    # No second controller factory call and no second subprocess.Popen!
    assert len(controller_instances) == 1
    assert len(captured_launch_args) == 1
    assert c1.is_running is True

    # loadfile command was sent via IPC with new url and start=30
    loadfile_calls = [cmd for cmd in sent_ipc_commands if cmd and cmd[0] == "loadfile"]
    assert len(loadfile_calls) >= 2  # first file and second file
    last_loadfile = loadfile_calls[-1]
    assert "http://ts/torrent2/1" in last_loadfile[1]
    assert any("start=30" in str(arg) for arg in last_loadfile)

    c1.stop()


def test_next_track_preserves_audio_and_subtitle_preferences_by_language(mpv_ipc_stream):
    """Verify that next_track remembers and automatically applies audio and subtitle preferences by language."""
    controller = MPVController()
    controller.is_running = True
    sent_commands = []
    controller.send_command = lambda cmd, **kw: sent_commands.append(cmd)

    # Episode 1: Initial track list
    ep1_tracks = [
        {"id": 1, "type": "audio", "lang": "eng"},
        {"id": 2, "type": "audio", "lang": "rus"},
        {"id": 3, "type": "sub", "lang": "eng"},
        {"id": 4, "type": "sub", "lang": "rus"},
    ]
    controller._properties["track-list"] = ep1_tracks

    # User manually selects Russian audio (id=2) and Russian subs (id=4)
    controller.set_property("aid", 2)
    controller.set_property("sid", 4)

    assert controller._saved_audio_pref["lang"] == "ru"
    assert controller._saved_audio_pref["index"] == 1
    assert controller._saved_sub_pref["lang"] == "ru"
    assert controller._saved_sub_pref["index"] == 1

    # Transition to Episode 2 via next_track
    controller.next_track("http://test.url/episode2.mkv", title="Episode 2")
    assert controller._pending_track_resolution is True

    # Episode 2 emits track list with different IDs (Russian audio is ID 10, Russian sub is ID 13)
    ep2_tracks = [
        {"id": 10, "type": "audio", "lang": "rus"},
        {"id": 11, "type": "audio", "lang": "eng"},
        {"id": 12, "type": "sub", "lang": "fra"},
        {"id": 13, "type": "sub", "lang": "rus"},
    ]

    controller._apply_preserved_track_preferences(ep2_tracks)

    # Verify that Russian tracks (aid=10, sid=13) were automatically selected
    assert ["set_property", "aid", 10] in sent_commands
    assert ["set_property", "sid", 13] in sent_commands


def test_next_track_falls_back_to_index_when_language_metadata_missing():
    """Verify that next_track falls back to track index matching when files lack language metadata."""
    controller = MPVController()
    controller.is_running = True
    sent_commands = []
    controller.send_command = lambda cmd, **kw: sent_commands.append(cmd)

    # Episode 1 tracks lack language tags
    ep1_tracks = [
        {"id": 1, "type": "audio"},
        {"id": 2, "type": "audio"},  # index 1
        {"id": 3, "type": "sub"},    # index 0
        {"id": 4, "type": "sub"},
    ]
    controller._properties["track-list"] = ep1_tracks

    # User selects 2nd audio track (id=2) and 1st subtitle track (id=3)
    controller.set_property("aid", 2)
    controller.set_property("sid", 3)

    assert controller._saved_audio_pref["index"] == 1
    assert controller._saved_sub_pref["index"] == 0

    # Transition to Episode 2
    controller.next_track("http://test.url/episode2.mkv", title="Episode 2")

    # Episode 2 has new track IDs without language tags
    ep2_tracks = [
        {"id": 101, "type": "audio"},
        {"id": 102, "type": "audio"},  # 2nd audio track should match index 1
        {"id": 103, "type": "sub"},    # 1st sub track should match index 0
        {"id": 104, "type": "sub"},
    ]

    controller._apply_preserved_track_preferences(ep2_tracks)

    assert ["set_property", "aid", 102] in sent_commands
    assert ["set_property", "sid", 103] in sent_commands


def test_next_track_preserves_subtitles_off():
    """Verify that when subtitles are disabled, next_track keeps subtitles disabled (sid=no)."""
    controller = MPVController()
    controller.is_running = True
    sent_commands = []
    controller.send_command = lambda cmd, **kw: sent_commands.append(cmd)

    # User turns subtitles off
    controller.set_property("sid", "no")
    assert controller._saved_sub_pref["mode"] == "off"

    # Transition to Episode 2
    controller.next_track("http://test.url/episode2.mkv", title="Episode 2")

    ep2_tracks = [
        {"id": 1, "type": "audio", "lang": "rus"},
        {"id": 2, "type": "sub", "lang": "rus"},
    ]
    controller._properties["sid"] = 2  # default or previous value

    controller._apply_preserved_track_preferences(ep2_tracks)

    assert ["set_property", "sid", "no"] in sent_commands


def test_mpv_startup_arguments_include_hdr_tone_mapping(monkeypatch, mpv_ipc_stream):
    """Verify MPV launch includes tone-mapping=auto and hdr-compute-peak=yes for HDR on SDR screens."""
    controller = MPVController()
    captured_args = []

    class DummyProcess:
        pid = 9876
        def poll(self):
            return None
        def terminate(self):
            pass
        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr("subprocess.Popen", lambda args, **kw: (captured_args.extend(args), DummyProcess())[1])
    monkeypatch.setattr(controller, "_open_pipe", lambda p: mpv_ipc_stream())
    monkeypatch.setattr(controller, "send_command", lambda cmd: None)
    monkeypatch.setattr(controller, "load_file", lambda *a, **kw: None)
    monkeypatch.setattr(controller, "_verify_cache", lambda: None)
    monkeypatch.setattr(controller, "_detect_loadfile_signature", lambda: None)

    controller.launch("mpv", "http://test.url/hdr_video.mkv", "HDR Tone Mapping Test")

    assert "--tone-mapping=auto" in captured_args
    assert "--hdr-compute-peak=yes" in captured_args

    controller.is_running = False


def test_mpv_metrics_properties_reporting():
    """Verify MPVController collects and calculates basic playback metrics (codec, dropped_frames, hwdec_active)."""
    controller = MPVController()

    # When stopped / empty
    metrics0 = controller.get_playback_metrics()
    assert metrics0 == {"codec": None, "dropped_frames": 0, "hwdec_active": False}

    # When active playback properties are set
    controller._properties["video-format"] = "hevc"
    controller._properties["decoder-frame-drop-count"] = 15
    controller._properties["hwdec-current"] = "d3d11va-copy"

    assert controller.current_codec == "hevc"
    assert controller.dropped_frames == 15
    assert controller.is_hwdec_active is True

    metrics = controller.get_playback_metrics()
    assert metrics["codec"] == "hevc"
    assert metrics["dropped_frames"] == 15
    assert metrics["hwdec_active"] is True




