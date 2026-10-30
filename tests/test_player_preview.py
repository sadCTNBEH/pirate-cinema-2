"""RAM-only preview policy, cancellation, and a real FFmpeg stdout decode."""
import json
import subprocess
import threading
from pathlib import Path
from unittest.mock import Mock

import pytest

from backend.infrastructure.mpv import preview
from backend.infrastructure.mpv.controller import MPVController


def test_sources_reject_network_before_stat(monkeypatch):
    monkeypatch.setattr(Path, 'stat', lambda *args: pytest.fail('network stat'))
    for source in ('https://host/film.mp4', 'file://host/share/film.mp4',
                   r'\\host\share\film.mp4', '//host/share/film.mp4', 'relative.mp4'):
        assert preview.local_source(source) is None


def test_ram_lru_bounds_and_release():
    cache = preview.ThumbnailCache(max_bytes=8, max_entries=2)
    cache.put('a', b'1111'); cache.put('b', b'2222')
    assert cache.get('a') == b'1111'
    cache.put('c', b'3333')
    assert cache.get('b') is None and cache.size == 8
    assert cache.put('large', bytes(9)) is None
    cache.clear()
    assert cache.size == 0 and not cache.frames


def test_stream_preview_disabled_without_export_or_download():
    controller = MPVController()
    controller._wid = 1
    commands = []
    controller.send_command = commands.append
    controller.load_file('http://invalid.test/stream?secret', 'Film')
    assert controller._preview.source is None
    controller._preview.request('1', '10')
    assert controller._preview.thread is None
    assert ['script-message', 'cinema-preview-mode', 'disabled'] in commands
    assert not any(c[0] == 'dump-cache' for c in commands)
    controller.stop()


def test_preview_ipc_does_not_seek(mpv_ipc_stream):
    controller = MPVController()
    controller.is_running = True
    session = Mock()
    controller._preview = session
    events = [{'event': 'client-message', 'args': ['cinema-preview', '7', '60']},
              {'event': 'client-message', 'args': ['cinema-preview']}]
    controller.pipe = mpv_ipc_stream(b''.join((json.dumps(e)+'\n').encode() for e in events))
    controller._reader_loop()
    session.request.assert_called_once_with('7', '60')
    session.cancel.assert_called_once()


def test_decoder_cancel_and_reuse_without_files(tmp_path, monkeypatch):
    source = tmp_path / 'film.mp4'
    source.write_bytes(b'fixture')
    monkeypatch.setattr(preview.shutil, 'which', lambda _: 'ffmpeg')
    started, done = threading.Event(), threading.Event()
    processes, results = [], []
    class Decoder:
        returncode = 0
        def __init__(self, args, **kwargs):
            assert args[-1] == 'pipe:1' and kwargs['stdout'] == subprocess.PIPE
            self.cancelled = threading.Event()
            processes.append(self)
            started.set()
        def communicate(self, timeout):
            if len(processes) == 1:
                assert self.cancelled.wait(2)
            return bytes(preview.FRAME_BYTES), b''
        def terminate(self):
            self.cancelled.set()
        kill = terminate
        def wait(self, timeout):
            return 0
    monkeypatch.setattr(preview.subprocess, 'Popen', Decoder)
    session = preview.PreviewSession(str(source), lambda *args: (results.append(args), done.set()))
    try:
        session.request('1', '11'); assert started.wait(2)
        session.request('2', '25'); assert done.wait(2)
        assert results[0][0] == '2' and processes[0].cancelled.is_set()
        done.clear()
        session.request('3', '26'); assert done.wait(2)
        assert len(processes) == 2 and results[-1][1] == results[0][1]
        assert list(tmp_path.iterdir()) == [source]
    finally:
        session.close()
    assert not session.thread.is_alive() and session.cache.size == 0


def test_real_ffmpeg_stdout_preview_no_files(tmp_path, monkeypatch):
    binary = preview.shutil.which('ffmpeg')
    if not binary:
        pytest.skip('FFmpeg unavailable')
    source = tmp_path / 'fixture.mp4'
    subprocess.run([binary, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    'testsrc2=size=320x180:rate=1', '-t', '7', '-threads', '1', str(source)],
                   check=True, timeout=15)
    before = set(tmp_path.rglob('*'))
    results, ready = [], threading.Event()
    session = preview.PreviewSession(str(source), lambda *args: (results.append(args), ready.set()))
    try:
        session.request('1', '5')
        assert ready.wait(12) and results[0][1]
        groups = json.loads(results[0][1])
        assert 1 < len(groups) <= 512
        assert all(len(c) == 6 and path.startswith('m ') for c, path in groups)
        assert session.cache.size <= preview.CACHE_BYTES
        assert set(tmp_path.rglob('*')) == before
    finally:
        session.close()


def test_standalone_custom_osd_uses_same_ram_preview(tmp_path):
    source=tmp_path/'film.mp4';source.write_bytes(b'fixture')
    c=MPVController();c._custom_osd=True
    commands=[];c.send_command=commands.append
    assert not c.is_embedded
    c.load_file(str(source),'Standalone Linux-style window')
    try:
        assert c._preview.source == source
        assert ['script-message','cinema-preview-mode','local'] in commands
    finally:
        c.stop()
