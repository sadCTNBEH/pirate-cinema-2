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
    assert controller._preview.source is None
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
