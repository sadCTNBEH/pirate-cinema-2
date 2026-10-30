import io
import os

import pytest

from backend.infrastructure.mpv.controller import MPVController


def test_mpv_reader_loop_handles_auto_and_no_properties():
    controller = MPVController()
    controller.is_running = True

    events_stream = io.BytesIO(
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


def test_mpv_reader_loop_resilient_to_callback_exception():
    controller = MPVController()
    controller.is_running = True

    events_stream = io.BytesIO(
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


def test_mpv_load_file_commands():
    controller = MPVController()
    controller.is_running = True
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
        -1,
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
        -1,
        "pause=no,start=150,sub-delay=0.0,audio-delay=0.0,aid=2,sid=3",
    ] in sent_commands
    assert ["set_property", "pause", False] in sent_commands


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("wid", [123456, None])
def test_mpv_launch_with_wid(monkeypatch, legacy, wid):
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
    monkeypatch.setattr(controller, "_open_pipe", lambda p: io.BytesIO())
    monkeypatch.setattr(controller, "send_command", lambda cmd: None)
    monkeypatch.setattr(controller, "load_file", lambda *a, **kw: None)
    monkeypatch.setattr(controller, "_verify_cache", lambda: None)

    controller.launch("mpv", "http://test.url/video.mkv", "Test Title", wid=wid)

    if wid is not None:
        assert "--wid=123456" in captured_args
        assert ("--osc=yes" if legacy else "--osc=no") in captured_args
        assert ("--input-doubleclick-time=0" in captured_args) is not legacy
        assert ("--cursor-autohide=1500" if legacy else "--cursor-autohide=no") in captured_args
        assert any(arg.startswith("--script=") and arg.endswith("cinema.lua") for arg in captured_args) is not legacy
        assert "--input-default-bindings=yes" in captured_args
        assert "--input-vo-keyboard=no" in captured_args
        assert "--input-builtin-dragging=no" in captured_args
        assert "--window-dragging=no" in captured_args
        assert "--input-cursor=yes" in captured_args
        assert "--keepaspect=yes" in captured_args
        assert "--fs" not in captured_args
        if os.name == "nt":
            assert "--gpu-api=d3d11" in captured_args
            assert "--gpu-context=d3d11" in captured_args
            assert "--gpu-api=opengl" not in captured_args
            assert "--gpu-context=win" not in captured_args
            assert "--hwdec=d3d11va-copy" in captured_args
    else:
        assert "--fs" in captured_args
        assert not any(arg.startswith("--wid=") for arg in captured_args)
        if os.name == "nt":
            assert "--gpu-api=opengl" in captured_args
            assert "--gpu-context=win" in captured_args
            assert "--hwdec=d3d11va-copy" in captured_args
    controller.is_running = False


def test_mpv_reader_loop_handles_fullscreen_property():
    controller = MPVController()
    controller.is_running = True

    events_stream = io.BytesIO(
        b'{"event":"property-change","id":6,"name":"fullscreen","data":true}\n'
        b'{"event":"property-change","id":6,"name":"fullscreen","data":false}\n'
    )
    controller.pipe = events_stream

    progress_calls = []
    controller.on_progress = lambda name, val: progress_calls.append((name, val))

    controller._reader_loop()

    assert ("fullscreen", True) in progress_calls
    assert ("fullscreen", False) in progress_calls


def test_mpv_reader_loop_handles_track_list():
    controller = MPVController()
    controller.is_running = True

    events_stream = io.BytesIO(
        b'{"event":"property-change","id":10,"name":"track-list","data":[{"id":1,"type":"audio","lang":"rus"}]}\n'
    )
    controller.pipe = events_stream

    progress_calls = []
    controller.on_progress = lambda name, val: progress_calls.append((name, val))

    controller._reader_loop()

    assert ("track-list", [{"id": 1, "type": "audio", "lang": "rus"}]) in progress_calls


