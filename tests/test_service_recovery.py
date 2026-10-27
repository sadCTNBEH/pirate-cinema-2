"""Failure/recovery policies use mock processes and HTTP only."""
import asyncio
import io
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.infrastructure.mpv.controller import MPVController
from backend.infrastructure.torrserver import process as ts
from backend.models.playback import PlaybackState
from backend.services.diagnostics import DiagnosticsService
from backend.services.playback import PlaybackService


@pytest.fixture
def managed(monkeypatch, tmp_path):
    binary = tmp_path / 'torrserver'
    binary.write_bytes(b'original binary')
    child = MagicMock(pid=42, returncode=1)
    child.poll.return_value = None
    for name, value in {
        '_process': child, '_last_error': None, '_last_failure': None, '_version': 'MatriX.145.2',
        '_active_url': 'http://127.0.0.1:8091', '_external_url': None,
        '_managed_config': ('http://127.0.0.1:8091', binary, tmp_path),
        '_desired_running': True, '_health_failures': 0, '_recovery_attempts': 0, '_retry_at': 0.0,
        '_service_state': 'running', '_stop_requested': threading.Event(), '_monitor_stop': threading.Event(),
        '_monitor_thread': None, '_lifecycle_lock': threading.RLock(), '_update_cache': None,
    }.items():
        monkeypatch.setattr(ts, name, value)
    monkeypatch.setattr(ts, '_probe', MagicMock(return_value=True))
    replacement = MagicMock(pid=43)
    replacement.poll.return_value = None

    def launch(*args, **kwargs):
        ts._process = replacement
        ts._last_error = None
        return True

    start = MagicMock(side_effect=launch)
    monkeypatch.setattr(ts, '_connect_or_start', start)
    return child, replacement, start, binary


def test_torrserver_unexpected_exit_recovers_after_backoff(managed):
    child, replacement, start, _ = managed
    child.poll.return_value = 1
    ts._monitor_tick(0)
    assert ts.get_status()['state'] == 'recovering'
    start.assert_not_called()
    ts._monitor_tick(1)
    start.assert_not_called()
    ts._monitor_tick(2)
    start.assert_called_once()
    assert ts._process is replacement
    assert ts.get_status()['state'] == 'running'


def test_temporary_slow_response_does_not_restart(managed):
    child, _, start, _ = managed
    ts._probe.side_effect = [False, False, True]
    for now in (0, 5, 10):
        ts._monitor_tick(now)
    start.assert_not_called()
    child.terminate.assert_not_called()
    assert ts._health_failures == 0


def test_confirmed_hang_restarts_only_owned_process(managed):
    child, _, start, _ = managed
    ts._probe.return_value = False
    for now in (0, 5, 10):
        ts._monitor_tick(now)
    assert ts.get_status()['state'] == 'recovering'
    child.terminate.assert_not_called()
    ts._monitor_tick(12)
    child.terminate.assert_called_once()
    start.assert_called_once()


def test_concurrent_recovery_spawns_once(managed):
    child, replacement, start, _ = managed
    child.poll.return_value = 1
    ts._monitor_tick(0)
    entered, release = threading.Event(), threading.Event()

    def launch(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        ts._process = replacement
        return True

    start.side_effect = launch
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(ts._monitor_tick, 2)
        assert entered.wait(2)
        pool.submit(ts._monitor_tick, 2).result(timeout=2)
        release.set()
        first.result(timeout=2)
    start.assert_called_once()


def test_recovery_budget_exhausted_and_not_reset_by_more_ticks(managed):
    child, _, start, _ = managed
    child.poll.return_value = 1
    start.side_effect = RuntimeError('not ready')
    for now in (0, 2, 7, 22, 100, 200):
        ts._monitor_tick(now)
    assert start.call_count == 3
    assert ts.get_status()['state'] == 'error'
    assert 'исчерпано' in ts.get_last_error()


def test_manual_stop_and_shutdown_cancel_recovery(managed):
    child, _, start, _ = managed
    child.poll.return_value = 1
    ts._monitor_tick(0)
    ts.stop()
    ts._monitor_tick(100)
    start.assert_not_called()
    assert ts.get_status()['state'] == 'stopped'
    ts._desired_running = True
    ts._stop_requested.clear()
    ts._monitor_tick(101)
    ts.shutdown_monitor()
    ts._monitor_tick(200)
    start.assert_not_called()


def test_stop_during_recovery_does_not_resurrect_process(managed):
    child, _, start, _ = managed
    child.poll.return_value = 1
    ts._monitor_tick(0)
    entered = threading.Event()

    def launch(*args, **kwargs):
        entered.set()
        assert ts._stop_requested.wait(2)
        raise RuntimeError('cancelled')

    start.side_effect = launch
    with ThreadPoolExecutor(max_workers=2) as pool:
        recovery = pool.submit(ts._monitor_tick, 2)
        assert entered.wait(2)
        stopping = pool.submit(ts.stop)
        recovery.result(timeout=3)
        stopping.result(timeout=3)
    ts._monitor_tick(100)
    start.assert_called_once()
    assert ts._process is None and not ts._desired_running


def test_external_service_is_never_recovered_or_replaced(managed):
    _, _, start, _ = managed
    ts._process = None
    ts._managed_config = None
    ts._external_url = 'http://127.0.0.1:8091'
    ts._probe.return_value = False
    ts._monitor_tick(100)
    start.assert_not_called()
    with pytest.raises(RuntimeError, match='Внешний'):
        ts.restart(ts._external_url)
    start.assert_not_called()


def test_update_check_reads_metadata_only_and_keeps_playback_binary(managed, monkeypatch):
    child, _, start, binary = managed
    response = MagicMock()
    response.json.return_value = {'tag_name': 'MatriX.147.1',
                                  'html_url': 'https://github.com/YouROK/TorrServer/releases/tag/MatriX.147.1'}
    client = MagicMock()
    client.__enter__.return_value.get.return_value = response
    monkeypatch.setattr(ts.httpx, 'Client', MagicMock(return_value=client))
    result = ts.check_update()
    assert result['update_available'] is True and result['install_supported'] is False
    assert binary.read_bytes() == b'original binary'
    assert ts._process is child
    start.assert_not_called()
    child.terminate.assert_not_called()
    request = client.__enter__.return_value.get.call_args.args[0]
    assert request == 'https://api.github.com/repos/YouROK/TorrServer/releases/latest'
    assert ts.check_update()['latest_version'] == result['latest_version']
    assert client.__enter__.return_value.get.call_count == 1


@pytest.mark.parametrize(('code', 'expected'), [(0, 'quit'), (7, 'crash'), (None, 'ipc_lost')])
def test_mpv_distinguishes_user_exit_crash_and_ipc_loss(code, expected):
    controller = MPVController()
    controller.process = MagicMock()
    controller.process.poll.return_value = code
    if code is None:
        controller.process.wait.side_effect = [subprocess.TimeoutExpired('mpv', 0.2), 0]
    controller.pipe = io.BytesIO(b'')
    controller.is_running = True
    reasons = []
    controller.on_end = reasons.append
    controller._reader_loop()
    assert reasons == [expected]
    assert controller.process is None and not controller.is_running


def playback():
    controller = MagicMock(is_running=True)
    service = PlaybackService(MagicMock(), MagicMock(), MagicMock(), lambda: controller,
                              MagicMock(), lambda: '')
    service.controllers['hash'] = controller
    service.active_states['hash'] = PlaybackState(hash='hash', file_id=4, file_name='S01E02.mkv',
                                                 timecode=333, duration=1800, audio_track=2)
    return service, controller


def test_crashed_mpv_saves_confirmed_position_and_resumes_only_on_request():
    service, controller = playback()
    service._save_state_to_db = AsyncMock()

    async def run():
        service.loop = asyncio.get_running_loop()
        service._handle_end('hash', 'crash')
        await asyncio.sleep(0.01)
        assert service.get_active_playback()['failure']['timecode'] == 333
        saved = service._save_state_to_db.call_args.args[0]
        assert saved.timecode == 333 and not saved.is_watched
        assert not service.controllers
        controller.launch.assert_not_called()

        async def launch(command):
            service._begin_launch()
            await asyncio.sleep(0)
            return 'launched'

        service.launch = AsyncMock(side_effect=launch)
        result = await service.recover()
        assert result == 'launched'
        command = service.launch.call_args.args[0]
        assert command.start_time == 333 and command.audio_track == 2 and command.file_id == 4

    asyncio.run(run())


def test_manual_stop_invalidates_pending_resume_and_launch():
    service, controller = playback()
    service._handle_end('hash', 'ipc_lost')
    service.stop()
    with pytest.raises(Exception, match='Нет прерванного'):
        asyncio.run(service.recover())
    generation = service._begin_launch()
    service.stop()
    with pytest.raises(RuntimeError, match='отменён'):
        service._launch_controller(controller, generation, {})
    controller.launch.assert_not_called()


def test_simultaneous_resume_requests_do_not_launch_two_players():
    service, _ = playback()
    service._handle_end('hash', 'crash')

    async def launch(command):
        service._begin_launch()
        await asyncio.sleep(0.01)
        return 'launched'

    service.launch = AsyncMock(side_effect=launch)

    async def run():
        results = await asyncio.gather(service.recover(), service.recover(), return_exceptions=True)
        assert results.count('launched') == 1
        assert service.launch.await_count == 1

    asyncio.run(run())


def test_shutdown_rejects_late_torrserver_start(managed):
    _, _, start, _ = managed
    ts.shutdown_monitor()
    with pytest.raises(RuntimeError, match='завершает'):
        ts.connect_or_start()
    start.assert_not_called()


def test_stop_racing_mpv_start_cancels_and_cleans_up_single_child():
    service, controller = playback()
    controller.is_running = False
    entered, cancel = threading.Event(), threading.Event()
    controller.cancel_start.side_effect = cancel.set

    def launch(**kwargs):
        entered.set()
        assert cancel.wait(2)

    controller.launch.side_effect = launch
    generation = service._begin_launch()
    cancel.clear()
    with ThreadPoolExecutor(max_workers=2) as pool:
        starting = pool.submit(service._launch_controller, controller, generation, {})
        assert entered.wait(2)
        stopping = pool.submit(service.stop)
        with pytest.raises(RuntimeError, match='отменён'):
            starting.result(timeout=3)
        stopping.result(timeout=3)
    controller.launch.assert_called_once()
    assert not service.controllers and not service.active_states


def test_restart_is_blocked_during_playback_but_update_check_is_read_only(managed):
    _, _, start, _ = managed
    diagnostics = DiagnosticsService(MagicMock(), playback_status_provider=lambda: {'state': 'running'})
    with pytest.raises(RuntimeError, match='остановите'):
        asyncio.run(diagnostics.restart_torrserver())
    start.assert_not_called()
