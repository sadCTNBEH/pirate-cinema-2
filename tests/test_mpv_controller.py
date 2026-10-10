import io

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
    assert end_calls == ["eof"]


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
        "pause=no,start=0",
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
        "pause=no,start=150,aid=2,sid=3",
    ] in sent_commands
    assert ["set_property", "pause", False] in sent_commands
