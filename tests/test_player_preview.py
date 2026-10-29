import io
import json
import subprocess
import threading
from pathlib import Path

import pytest

from backend.infrastructure.mpv import preview
from backend.infrastructure.mpv.controller import MPVController


@pytest.fixture
def local_video(tmp_path, monkeypatch):
    source = tmp_path / "film.mp4"
    source.write_bytes(b"fixture")
    cache = preview.ThumbnailCache(tmp_path / "cache")
    monkeypatch.setattr(preview, "thumbnail_cache", lambda: cache)
    return source, cache


def test_source_policy_never_reads_network(monkeypatch):
    def no_stat(*args):
        pytest.fail("Network sources must be rejected before reading data")
    monkeypatch.setattr(Path, "stat", no_stat)
    for source in ("https://secret:token@host/film.mp4", "http://localhost:8090/stream/film.mp4?play",
                   "file://server/share/movie.mp4", r"\\server\share\movie.mp4", "//server/share/movie.mp4",
                   "av://lavfi:testsrc", "relative.mp4"):
        assert preview.local_source(source) is None


def test_cache_reuses_and_limits_bytes_and_entries(tmp_path):
    cache = preview.ThumbnailCache(tmp_path, max_bytes=preview.FRAME_BYTES*2, max_entries=2)
    def put(key):
        temp = tmp_path / "frame.part"
        temp.write_bytes(bytes(preview.FRAME_BYTES))
        return cache.put(key, temp)
    first = put("first")
    put("second")
    assert cache.get("first") == first
    put("third")
    assert cache.get("second") is None
    assert cache.get("first") == first
    assert len(list(tmp_path.glob("*.bgra"))) == 2
    assert sum(p.stat().st_size for p in tmp_path.glob("*.bgra")) <= cache.max_bytes


def test_cache_removes_old_incomplete_and_corrupt_files(tmp_path):
    import os
    (tmp_path / "incomplete.part").write_bytes(b"x")
    old = tmp_path / "old.bgra"
    old.write_bytes(bytes(preview.FRAME_BYTES))
    os.utime(old, (1, 1))
    (tmp_path / "bad.bgra").write_bytes(b"corrupt")
    preview.ThumbnailCache(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_identity_separates_videos_positions_and_file_replacements(local_video):
    source, _ = local_video
    key = preview.frame_key(source, 0)
    other = source.with_name("other.mp4")
    other.write_bytes(source.read_bytes())
    assert preview.frame_key(other, 0) != key
    assert preview.frame_key(source, 5) != key
    source.write_bytes(b"replacement")
    assert preview.frame_key(source, 0) != key


def test_missing_ffmpeg_returns_neutral_without_playback_commands(local_video, monkeypatch):
    source, _ = local_video
    monkeypatch.setattr(preview.shutil, "which", lambda _: None)
    result, ready = [], threading.Event()
    session = preview.PreviewSession(str(source), lambda *args: (result.append(args), ready.set()))
    try:
        session.request("1", "22")
        assert ready.wait(2)
        assert result == [("1", "")]
    finally:
        session.close()
    assert not session.thread.is_alive()


def test_latest_request_cancels_worker_deduplicates_and_cleans(local_video, monkeypatch):
    source, cache = local_video
    started, finished = threading.Event(), threading.Event()
    processes, results = [], []
    monkeypatch.setattr(preview.shutil, "which", lambda _: "ffmpeg")
    class Decoder:
        def __init__(self, args, **kwargs):
            self.args, self.cancelled = args, threading.Event()
            processes.append(self)
            Path(args[-1]).write_bytes(bytes(preview.FRAME_BYTES))
            started.set()
        def wait(self, timeout):
            if len(processes) == 1:
                assert self.cancelled.wait(2)
            return 0
        def terminate(self):
            self.cancelled.set()
        kill = terminate
    monkeypatch.setattr(preview.subprocess, "Popen", Decoder)
    session = preview.PreviewSession(str(source), lambda *args: (results.append(args), finished.set()))
    try:
        session.request("1", "11")
        assert started.wait(2)
        session.request("1", "11")
        assert len(processes) == 1
        session.request("2", "25")
        assert finished.wait(2)
        assert len(processes) == 2
        assert results[0][0] == "2"
        assert processes[0].cancelled.is_set()
        finished.clear()
        session.request("3", "26")
        assert finished.wait(2)
        assert len(processes) == 2, "Same five-second bucket must use the cache"
        assert results[-1][1] == results[0][1]
    finally:
        session.close()
    assert not list(cache.directory.glob("*.part"))


def test_video_change_during_generation_never_publishes_old_image(local_video, monkeypatch):
    source, cache = local_video
    started, cancelled = threading.Event(), threading.Event()
    monkeypatch.setattr(preview.shutil, "which", lambda _: "ffmpeg")
    class Decoder:
        def __init__(self, args, **kwargs):
            Path(args[-1]).write_bytes(bytes(preview.FRAME_BYTES))
            started.set()
        def wait(self, timeout):
            assert cancelled.wait(2)
            return 0
        def terminate(self):
            cancelled.set()
        kill = terminate
    monkeypatch.setattr(preview.subprocess, "Popen", Decoder)
    published = []
    controller = MPVController()
    controller._wid = 1
    controller.send_command = published.append
    old = preview.PreviewSession(str(source), lambda *args: published.append(args))
    controller._preview = old
    old.request("old", "10")
    assert started.wait(2)
    controller.load_file("https://host/new-film.mp4?private=token", "New film")
    assert cancelled.is_set() and not old.thread.is_alive()
    assert all(isinstance(command, list) for command in published)
    assert not list(cache.directory.glob("*.part"))
    assert isinstance(controller._preview, preview.StreamPreviewSession)
    assert "token" not in controller._preview.source
    controller._preview.close()


def test_preview_ipc_does_not_seek_or_change_playback():
    from unittest.mock import Mock
    controller = MPVController()
    controller.is_running = True
    session = Mock()
    controller._preview = session
    commands = []
    controller.send_command = commands.append
    events = [{"event": "client-message", "args": ["cinema-preview", "7", "60"]},
              {"event": "client-message", "args": ["cinema-preview"]}]
    controller.pipe = io.BytesIO(b"".join((json.dumps(e)+"\n").encode() for e in events))
    controller._reader_loop()
    session.request.assert_called_once_with("7", "60")
    session.cancel.assert_called_once()
    assert commands == []


def test_real_ffmpeg_produces_small_bgra_frame(local_video):
    binary = preview.shutil.which("ffmpeg")
    if not binary:
        pytest.skip("FFmpeg is not installed")
    source, cache = local_video
    subprocess.run([binary, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=1",
                    "-t", "7", "-threads", "1", str(source)], check=True, timeout=15)
    results, ready = [], threading.Event()
    session = preview.PreviewSession(str(source), lambda *args: (results.append(args), ready.set()))
    try:
        session.request("1", "5")
        assert ready.wait(12)
        path = Path(results[0][1])
        assert path.stat().st_size == preview.FRAME_BYTES
        pixels = path.read_bytes()
        assert pixels[3] == 0, "Rounded thumbnail corner must be transparent"
        assert pixels[(preview.WIDTH*20+20)*4+3] == 255
        assert len(list(cache.directory.glob("*.bgra"))) == 1
    finally:
        session.close()


def test_buffer_ranges_validate_real_packet_intervals():
    state = {"seekable-ranges": [{"start": 0, "end": 20}, {"start": 40, "end": 65}]}
    assert preview.buffered_range(state, 10) == (0, 20)
    assert preview.buffered_range(state, 45) == (40, 65)
    for position in (-1, 20, 25, 65, 999):
        assert preview.buffered_range(state, position) is None
    for invalid in (None, {}, {"seekable-ranges": "bad"},
                    {"seekable-ranges": [None, {}, {"start": "nan", "end": 50}]}):
        assert preview.buffered_range(invalid, 10) is None


def test_stream_reads_only_buffered_excerpt_reuses_sparse_frames(local_video, monkeypatch):
    _, cache = local_video
    exports, decodes, results = [], [], []
    ready = threading.Event()
    state = {"seekable-ranges": [{"start": 20, "end": 80}]}
    monkeypatch.setattr(preview.shutil, "which", lambda _: "ffmpeg")
    def export(path, position, cancelled):
        exports.append(position)
        path.write_bytes(b"local cached packets")
        return True
    session = preview.StreamPreviewSession("http://localhost:8090/stream?private=token",
        lambda *args: (results.append(args), ready.set()), export, lambda: state)
    def decode(source, key, serial, position=None):
        decodes.append(str(source))
        assert str(source).endswith('.excerpt.mkv') and position is None
        temp = cache.directory / "test.part"
        temp.write_bytes(bytes(preview.FRAME_BYTES))
        return cache.put(key, temp)
    monkeypatch.setattr(session, "_decode", decode)
    try:
        session.request("1", "51")
        assert ready.wait(2) and results[-1][1]
        ready.clear()
        session.request("2", "59")
        assert ready.wait(2)
        assert exports == [50] and len(decodes) == 1
        assert results[-1][1] == results[0][1]
        ready.clear()
        session.request("3", "200")
        assert ready.wait(2) and results[-1] == ("3", "")
        assert exports == [50], "Outside the buffer must not read or download anything"
    finally:
        session.close()
    assert not list(cache.directory.glob("*.excerpt.mkv"))


def test_stream_cancellation_discards_excerpt(local_video, monkeypatch):
    _, cache = local_video
    started, finish = threading.Event(), threading.Event()
    published = []
    monkeypatch.setattr(preview.shutil, "which", lambda _: "ffmpeg")
    def export(path, position, cancelled):
        started.set()
        assert finish.wait(2)
        path.write_bytes(b"cached packets")
        return True
    session = preview.StreamPreviewSession("http://localhost/torrent", lambda *args: published.append(args),
        export, lambda: {"seekable-ranges": [{"start": 0, "end": 30}]})
    session.request("1", "10")
    assert started.wait(2)
    session.cancel()
    finish.set()
    session.close()
    assert published == [] and list(cache.directory.iterdir()) == []


def test_export_command_uses_only_buffer_without_seeking(tmp_path):
    controller = MPVController()
    controller.is_running = True
    controller._preview_cache_state = {"seekable-ranges": [{"start": 0, "end": 60}]}
    commands = []
    def send(command, request_id=None):
        commands.append(command)
        ready, result, _ = controller._preview_exports[request_id]
        result.append(True)
        ready.set()
    controller.send_command = send
    path = tmp_path / "test.excerpt.mkv"
    assert controller._export_preview(path, 40, lambda: False)
    assert commands == [["dump-cache", 40, 40.25, str(path)]]
    assert controller._preview_exports == {}
    assert not controller._export_preview(path, 80, lambda: False)
    controller._preview_buffering = True
    assert not controller._export_preview(path, 40, lambda: False)
    assert len(commands) == 1


def test_cancelled_export_removes_late_mpv_file(tmp_path):
    controller = MPVController()
    controller.is_running = True
    controller._preview_cache_state = {"seekable-ranges": [{"start": 0, "end": 60}]}
    commands = []
    controller.send_command = lambda command, **kwargs: commands.append(command)
    path = tmp_path / "late.excerpt.mkv"
    checks = []
    def cancelled():
        checks.append(True)
        return len(checks) > 1
    assert not controller._export_preview(path, 10, cancelled)
    request_id = controller._preview_request_id
    assert commands[-1] == ["dump-cache", "no", "no", ""]
    assert len(controller._preview_exports) == 1
    assert not controller._export_preview(path, 10, lambda: False)
    path.write_bytes(b"late cached packets")
    controller.pipe = io.BytesIO((json.dumps({"request_id": request_id, "error": "success"})+"\n").encode())
    controller._reader_loop()
    assert not path.exists() and controller._preview_exports == {}


def test_missing_ffmpeg_does_not_export_or_download_stream(local_video, monkeypatch):
    from unittest.mock import Mock
    monkeypatch.setattr(preview.shutil, "which", lambda _: None)
    export = Mock()
    session = preview.StreamPreviewSession("http://localhost/stream", Mock(), export,
        lambda: {"seekable-ranges": [{"start": 0, "end": 60}]})
    assert session._generate(20, 0) is None
    export.assert_not_called()
    session.close()


def test_real_mpv_buffer_preview_ahead_of_playback(local_video, monkeypatch):
    import time

    root = Path(__file__).resolve().parents[1]
    bundled = root / 'mpv' / 'mpv.com'
    mpv = str(bundled) if bundled.is_file() else preview.shutil.which('mpv')
    ffmpeg = preview.shutil.which('ffmpeg')
    if not mpv or not ffmpeg:
        pytest.skip('MPV and FFmpeg are required')
    source, cache = local_video
    subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    'testsrc2=size=320x180:rate=10', '-f', 'lavfi', '-i',
                    'sine=frequency=440:sample_rate=48000', '-t', '25', '-threads', '1',
                    '-g', '20', '-c:a', 'aac', '-b:a', '64k', str(source)], check=True, timeout=15)
    monkeypatch.setattr('backend.infrastructure.mpv.controller.get_data_dir', lambda: source.parent)
    monkeypatch.setattr('backend.infrastructure.mpv.controller.config.MPV_ARGS',
                        ['--no-config', '--vo=null', '--ao=null', '--idle=yes', '--cache=yes'])
    controller = MPVController()
    position = []
    paused = threading.Event()
    def progress(name, value):
        if name == 'time-pos' and isinstance(value, (float, int)):
            position.append(value)
            controller.send_command(['set_property', 'pause', True])
        if name == 'pause' and value is True:
            paused.set()
    controller.on_progress = progress
    session = None
    try:
        controller.launch(mpv, str(source), 'Buffer preview integration')
        assert paused.wait(3)
        deadline = time.monotonic() + 3
        while not preview.buffered_range(controller._preview_cache_state, 10):
            assert time.monotonic() < deadline, 'MPV must buffer the future target'
            time.sleep(0.02)
        before = position[-1]
        results, ready = [], threading.Event()
        session = preview.StreamPreviewSession('http://invalid.test/do-not-fetch',
            lambda *args: (results.append(args), ready.set()), controller._export_preview,
            lambda: controller._preview_cache_state)
        session.request('1', '12')
        assert ready.wait(5), 'Preview request must finish'
        assert results[-1][1], 'Buffered future position must have a thumbnail'
        path = Path(results[-1][1])
        assert path.stat().st_size == preview.FRAME_BYTES
        assert before < 2 and position[-1] < 2, 'Main MPV must not seek to the preview position'
        assert not list(cache.directory.glob('*.excerpt.mkv'))
    finally:
        if session:
            session.close()
        controller.stop()
