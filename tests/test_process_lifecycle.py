"""Integration tests for child process lifecycle and cleanup (MPV, TorrServer, FFmpeg).

Tests verify:
1. Process ownership tracking (TorrServer, MPV) and non-interference with external processes.
2. Graceful stop with timeouts: terminate (SIGTERM) -> wait -> kill (SIGKILL).
3. Idempotent stop operations.
4. Duplicate click protection (stopping previous instance before spawning new one).
5. App unified cleanup handler when the event loop or lifespan terminates abnormally.
"""

import asyncio
import io
import subprocess
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app import (
    app,
    application_lifespan,
    cleanup_child_processes,
    cleanup_child_processes_sync,
    register_loop_cleanup,
)
from backend.infrastructure.mpv.controller import MPVController
from backend.infrastructure.torrserver import process as torr_process


class DummyChildProcess:
    """Simulates a subprocess.Popen child process with lifecycle hooks."""

    def __init__(self, pid: int = 12345):
        self.pid = pid
        self.returncode = None
        self._poll_result = None
        self.terminated = False
        self.killed = False
        self.wait_calls = []

    def poll(self):
        return self._poll_result

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True
        self._poll_result = -9
        self.returncode = -9

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        if self._poll_result is not None:
            return self._poll_result
        return 0


# =====================================================================
# TorrServer Process Ownership & Lifecycle Tests
# =====================================================================


def test_torrserver_external_process_is_not_terminated(monkeypatch):
    """External TorrServer (launched by user) must not be owned or stopped."""
    monkeypatch.setattr(torr_process, "_process", None)
    monkeypatch.setattr(torr_process, "_owned_pid", None)
    monkeypatch.setattr(torr_process, "_external_url", "http://127.0.0.1:8090")
    monkeypatch.setattr(torr_process, "_managed_config", None)
    monkeypatch.setattr(torr_process, "_probe", lambda url: True)

    assert not torr_process.is_owned()
    assert torr_process.get_pid() is None

    # Stop must be a safe no-op that does not raise and does not kill external process
    torr_process.stop()
    assert not torr_process.is_owned()
    assert torr_process.get_active_url() is None


def test_torrserver_pid_mismatch_prevents_unowned_termination(monkeypatch):
    """If the PID does not match the tracked owned PID, stop() refuses to kill it."""
    dummy = DummyChildProcess(pid=9999)
    monkeypatch.setattr(torr_process, "_process", dummy)
    monkeypatch.setattr(torr_process, "_owned_pid", 1111)  # Mismatch

    torr_process.stop()

    assert not dummy.terminated
    assert not dummy.killed
    assert torr_process.get_pid() is None


def test_torrserver_graceful_stop_and_sigkill_escalation(monkeypatch):
    """Graceful stop calls terminate(SIGTERM), waits, then escalates to kill(SIGKILL) on timeout."""
    dummy = DummyChildProcess(pid=5555)

    # First wait raises TimeoutExpired, second wait after kill succeeds
    dummy.wait = MagicMock(side_effect=[subprocess.TimeoutExpired("torrserver", 5.0), 0])

    monkeypatch.setattr(torr_process, "_process", dummy)
    monkeypatch.setattr(torr_process, "_owned_pid", 5555)
    monkeypatch.setattr(torr_process, "_active_url", "http://127.0.0.1:8090")

    assert torr_process.is_owned()
    assert torr_process.get_pid() == 5555

    torr_process.stop()

    assert dummy.terminated
    assert dummy.killed
    assert dummy.wait.call_count == 2
    first_wait_timeout = (
        dummy.wait.call_args_list[0].kwargs.get("timeout")
        or (dummy.wait.call_args_list[0].args[0] if dummy.wait.call_args_list[0].args else None)
    )
    assert first_wait_timeout == 5.0
    assert not torr_process.is_owned()

    # Idempotent: repeated stop() is safe and does not crash
    torr_process.stop()


# =====================================================================
# MPV Controller Ownership & Duplicate Click Protection Tests
# =====================================================================


def test_mpv_controller_ownership_and_pid():
    controller = MPVController()
    assert not controller.is_owned()
    assert controller.get_pid() is None

    dummy = DummyChildProcess(pid=7777)
    controller.process = dummy
    controller._owned_pid = 7777

    assert controller.is_owned()
    assert controller.get_pid() == 7777

    controller.stop()
    assert dummy.terminated
    assert not controller.is_owned()
    assert controller.get_pid() is None

    # Idempotent: calling stop() again is safe
    controller.stop()


def test_mpv_controller_pid_mismatch_protection():
    controller = MPVController()
    dummy = DummyChildProcess(pid=8888)
    controller.process = dummy
    controller._owned_pid = 4444  # Mismatch

    controller.stop()
    # Mismatched process must not be terminated
    assert not dummy.terminated
    assert not dummy.killed


def test_mpv_controller_sigkill_on_timeout():
    controller = MPVController()
    dummy = DummyChildProcess(pid=9990)
    dummy.wait = MagicMock(side_effect=[subprocess.TimeoutExpired("mpv", 2.0), 0])
    controller.process = dummy
    controller._owned_pid = 9990

    controller.stop()

    assert dummy.terminated
    assert dummy.killed
    assert dummy.wait.call_count == 2
    first_wait_timeout = (
        dummy.wait.call_args_list[0].kwargs.get("timeout")
        or (dummy.wait.call_args_list[0].args[0] if dummy.wait.call_args_list[0].args else None)
    )
    assert first_wait_timeout == 2.0


def test_mpv_controller_launch_stops_existing_process(monkeypatch):
    """Repeated clicks or launching when an existing process is alive stops it first."""
    controller = MPVController()
    old_proc = DummyChildProcess(pid=1001)
    controller.process = old_proc
    controller._owned_pid = 1001
    controller.is_running = True

    new_proc = DummyChildProcess(pid=1002)

    def mock_popen(*args, **kwargs):
        return new_proc

    monkeypatch.setattr("subprocess.Popen", mock_popen)
    monkeypatch.setattr(controller, "_open_pipe", lambda name: io.BytesIO())
    monkeypatch.setattr(controller, "send_command", lambda *a, **kw: None)
    monkeypatch.setattr(controller, "load_file", lambda *a, **kw: None)
    monkeypatch.setattr(controller, "_verify_cache", lambda: None)
    monkeypatch.setattr(controller, "_detect_loadfile_signature", lambda: None)
    monkeypatch.setattr(controller, "_reader_loop", lambda: None)
    monkeypatch.setattr("backend.infrastructure.mpv.controller.config.MPV_ARGS", [])

    import builtins
    orig_open = builtins.open

    def mock_open(file, *args, **kwargs):
        if str(file) == controller.pipe_name:
            return io.BytesIO()
        return orig_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", mock_open)

    controller.launch("mpv", "http://example.com/video.mkv", "Title")

    # Old process must have been stopped and terminated
    assert old_proc.terminated
    # New process is now the active one
    assert controller.process is new_proc
    assert controller.get_pid() == 1002

    controller.stop()
    assert new_proc.terminated


# =====================================================================
# Unified Cleanup Handler Tests (MPV, TorrServer, FFmpeg)
# =====================================================================


@pytest.mark.asyncio
async def test_cleanup_child_processes_stops_all_components(monkeypatch):
    """Async cleanup_child_processes unloads TorrServer, MPV, and FFmpeg sessions."""
    # 1. Setup TorrServer mock
    torr_dummy = DummyChildProcess(pid=3001)
    monkeypatch.setattr(torr_process, "_process", torr_dummy)
    monkeypatch.setattr(torr_process, "_owned_pid", 3001)

    # 2. Setup PlaybackService (MPV) mock
    stop_all_mock = AsyncMock()
    mock_playback = MagicMock()
    mock_playback.stop_all = stop_all_mock
    monkeypatch.setattr("backend.api.deps.get_playback_service", lambda: mock_playback)

    # 3. Setup MobileSession (FFmpeg) mock
    from backend.services.mobile import mobile_access

    mock_session = MagicMock()
    mock_session.close = AsyncMock()
    mobile_access.sessions["test_session"] = mock_session

    try:
        await cleanup_child_processes()

        assert torr_dummy.terminated
        assert torr_process.get_pid() is None
        stop_all_mock.assert_awaited_once()
        mock_session.close.assert_awaited_once()
        assert len(mobile_access.sessions) == 0

        # Idempotence test: calling again is completely safe
        await cleanup_child_processes()
    finally:
        mobile_access.sessions.clear()


def test_cleanup_child_processes_sync_kills_ffmpeg_and_mpv(monkeypatch):
    """Synchronous cleanup kills active FFmpeg processes and stops MPV/TorrServer."""
    torr_dummy = DummyChildProcess(pid=4001)
    monkeypatch.setattr(torr_process, "_process", torr_dummy)
    monkeypatch.setattr(torr_process, "_owned_pid", 4001)

    mock_playback = MagicMock()
    monkeypatch.setattr("backend.api.deps.get_playback_service", lambda: mock_playback)

    from backend.services.mobile import mobile_access

    ffmpeg_dummy = DummyChildProcess(pid=4002)
    mock_session = MagicMock()
    mock_session.ffmpeg_process = ffmpeg_dummy
    mobile_access.sessions["ffmpeg_test"] = mock_session

    try:
        cleanup_child_processes_sync()

        assert torr_dummy.terminated
        assert ffmpeg_dummy.terminated
        mock_playback.stop.assert_called_once()
        assert len(mobile_access.sessions) == 0
    finally:
        mobile_access.sessions.clear()


def test_event_loop_close_triggers_cleanup(monkeypatch):
    """When an asyncio event loop is closed, the registered hook cleans up child processes."""
    loop = asyncio.new_event_loop()
    register_loop_cleanup(loop)

    torr_dummy = DummyChildProcess(pid=5001)
    monkeypatch.setattr(torr_process, "_process", torr_dummy)
    monkeypatch.setattr(torr_process, "_owned_pid", 5001)

    mock_playback = MagicMock()
    monkeypatch.setattr("backend.api.deps.get_playback_service", lambda: mock_playback)

    assert not torr_dummy.terminated

    # Closing the loop must invoke cleanup
    loop.close()

    assert torr_dummy.terminated
    mock_playback.stop.assert_called_once()


@pytest.mark.asyncio
async def test_application_lifespan_abnormal_exit_cleans_up(monkeypatch):
    """Even if an unhandled error occurs during lifespan execution, cleanup is executed."""
    torr_dummy = DummyChildProcess(pid=6001)
    monkeypatch.setattr(torr_process, "_process", torr_dummy)
    monkeypatch.setattr(torr_process, "_owned_pid", 6001)
    monkeypatch.setattr(torr_process, "connect_or_start", lambda *a, **kw: True)
    monkeypatch.setattr(torr_process, "start_monitor", lambda: None)
    monkeypatch.setattr(torr_process, "shutdown_monitor", lambda: None)

    mock_playback = MagicMock()
    mock_playback.stop_all = AsyncMock()
    monkeypatch.setattr("backend.api.deps.get_playback_service", lambda: mock_playback)

    # Simulate an error within lifespan
    with pytest.raises(RuntimeError, match="Simulated abnormal crash"):
        async with application_lifespan(app):
            raise RuntimeError("Simulated abnormal crash")

    # Verify that cleanup still executed in finally block
    assert torr_dummy.terminated
    mock_playback.stop_all.assert_awaited_once()


# =====================================================================
# Part 2: Background Task Cancellation, Session Reset & Tray Shutdown
# =====================================================================


@pytest.mark.asyncio
async def test_playback_cancel_background_tasks_on_stop_all(monkeypatch, tmp_path):
    """PlaybackService.stop_all() must cancel all background asyncio tasks and preparation."""
    from backend.services.playback import PlaybackService

    service = PlaybackService(
        playback_repo=MagicMock(),
        history_repo=MagicMock(),
        metadata_repo=MagicMock(),
        mpv_controller_factory=lambda: MPVController(),
        torrserver_client=MagicMock(),
        settings_provider=lambda: "http://127.0.0.1:8090",
    )
    service.loop = asyncio.get_running_loop()

    # Create dummy background tasks
    async def dummy_bg_coro():
        try:
            await asyncio.sleep(100)
        except asyncio.CancelledError:
            raise

    task1 = asyncio.create_task(dummy_bg_coro())
    task2 = asyncio.create_task(dummy_bg_coro())
    service.track_task(task1)
    service._segment_tasks.add(task2)

    # Create a dummy preparation future
    dummy_prep = asyncio.Future()
    service._preparation = dummy_prep

    assert not task1.done()
    assert not task2.done()
    assert not dummy_prep.done()

    await service.stop_all()

    assert task1.cancelled() or task1.done()
    assert task2.cancelled() or task2.done()
    assert dummy_prep.cancelled()
    assert len(service._background_tasks) == 0
    assert len(service._segment_tasks) == 0


def test_playback_cleanup_temp_resources(tmp_path):
    """cleanup_temp_resources() unlinks tracked temporary socket files."""
    from backend.services.playback import PlaybackService

    service = PlaybackService(
        playback_repo=MagicMock(),
        history_repo=MagicMock(),
        metadata_repo=MagicMock(),
        mpv_controller_factory=lambda: MPVController(),
        torrserver_client=MagicMock(),
        settings_provider=lambda: "http://127.0.0.1:8090",
    )

    temp_socket = tmp_path / "mpv-ipc-test.sock"
    temp_socket.touch()
    assert temp_socket.exists()

    service._temp_socket_paths.add(temp_socket)

    service.cleanup_temp_resources()

    assert not temp_socket.exists()
    assert len(service._temp_socket_paths) == 0


def test_tray_exit_invokes_unified_shutdown():
    """Tray exit event calls the registered unified shutdown service."""
    from backend.services import tray

    shutdown_called = False

    def mock_shutdown():
        nonlocal shutdown_called
        shutdown_called = True

    tray.set_shutdown_service(mock_shutdown)
    tray._handle_exit()

    assert shutdown_called
    tray.stop_tray()


def test_gui_shutdown_application_idempotency(monkeypatch):
    """shutdown_application() cleans up window, tray, and server, and is idempotent."""
    import backend.gui as gui

    monkeypatch.setattr(gui, "_shutdown_in_progress", threading.Event())

    mock_server = MagicMock()
    mock_server.should_exit = False

    mock_proc = DummyChildProcess(pid=9991)

    mock_window = MagicMock()
    monkeypatch.setattr(gui, "_window", mock_window)

    sync_cleanup_mock = MagicMock()
    monkeypatch.setattr("backend.app.cleanup_child_processes_sync", sync_cleanup_mock)

    # First call: executes cleanup
    gui.shutdown_application(mock_server, mock_proc, timeout=0.1)

    assert mock_server.should_exit is True
    assert mock_proc.terminated is True
    mock_window.destroy.assert_called_once()
    sync_cleanup_mock.assert_called_once()

    # Second call: idempotent, does not execute twice
    gui.shutdown_application(mock_server, mock_proc, timeout=0.1)
    assert sync_cleanup_mock.call_count == 1

