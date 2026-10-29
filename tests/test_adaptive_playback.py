import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.models.playback import PlaybackState
from backend.services.playback import PlaybackService


def player():
    ts = MagicMock()
    ts.torrent_video_files = AsyncMock(return_value=[
        {'id': 5, 'name': 'S01E02.mkv'}, {'id': 1, 'name': 'S01E01.mkv'},
    ])
    ts.stream_url.return_value = 'http://localhost/stream-next'
    controller = MagicMock(is_running=True)
    service = PlaybackService(MagicMock(), MagicMock(), MagicMock(), lambda: controller, ts, lambda: 'http://localhost')
    state = PlaybackState(hash='series', file_id=1, file_name='S01E01.mkv', duration=600, is_ready=True)
    service.controllers['series'] = controller
    service.active_states['series'] = state
    service._schedule_save = MagicMock()
    return service, state, controller, ts


async def drain():
    for _ in range(10):
        await asyncio.sleep(0.002)


@pytest.mark.asyncio
async def test_stale_seek_is_discarded_latest_seek_is_exact():
    service, state, controller, _ = player()
    service._seek_epoch = 2
    await asyncio.gather(service._seek_from_osd('series', state, 1, 50),
                         service._seek_from_osd('series', state, 2, 180))
    controller.send_command.assert_called_once_with(['seek', 180.0, 'absolute+exact'])
    controller.send_command.reset_mock()
    service._begin_launch()
    await service._seek_from_osd('series', state, 2, 220)
    controller.send_command.assert_not_called()


@pytest.mark.asyncio
async def test_other_input_supersedes_pending_osd_seek_and_invalid_time_is_ignored():
    service, state, controller, _ = player()
    service._seek_epoch = 1
    service.send_command(['seek', 10, 'relative'])
    await service._seek_from_osd('series', state, 1, 300)
    await service._seek_from_osd('series', state, 2, float('nan'))
    controller.send_command.assert_called_once_with(['seek', 10, 'relative'])


@pytest.mark.asyncio
async def test_prepare_next_once_without_opening_video_stream_and_use_prepared_target():
    service, state, controller, ts = player()
    service.loop = asyncio.get_running_loop()
    await service._refresh_next_available('series')
    controller.send_command.reset_mock()
    ts.torrent_video_files.reset_mock()
    for position in range(512, 530):
        service._handle_progress('series', 'time-pos', position)
    await drain()
    assert service._prepared_target(state)['file']['id'] == 5
    ts.stream_url.assert_called_once_with('http://localhost', 'series', 5, 'S01E02.mkv')
    ts.torrent_video_files.assert_not_awaited()
    controller.send_command.assert_not_called()
    service.launch = AsyncMock(return_value='launched')
    assert await service.play_next_file('series', 1)
    kwargs = service.launch.await_args.kwargs
    assert kwargs['command'].file_id == 5
    assert kwargs['command'].audio_track is None and kwargs['command'].subtitle_track is None
    assert kwargs['prepared_url'] == 'http://localhost/stream-next'
    ts.torrent_video_files.assert_not_awaited()


@pytest.mark.asyncio
async def test_prepare_failure_keeps_normal_launch_working():
    service, _, _, ts = player()
    service.loop = asyncio.get_running_loop()
    await service._refresh_next_available('series')
    ts.stream_url.side_effect = OSError('server unavailable')
    service._handle_progress('series', 'time-pos', 520)
    await drain()
    assert service._prepared_next is None
    service.launch = AsyncMock(return_value='launched')
    ts.torrent_video_files.reset_mock()
    assert await service.play_next_file('series', 1)
    ts.torrent_video_files.assert_awaited_once()
    assert 'prepared_url' not in service.launch.await_args.kwargs


@pytest.mark.asyncio
@pytest.mark.parametrize('cancel', ['stop', 'change', 'disable', 'buffering', 'shutdown'])
async def test_online_preparation_is_cancelled(cancel, monkeypatch):
    service, state, _, _ = player()
    service.loop = asyncio.get_running_loop()
    state.is_online = True
    state.playlist_id = 'playlist'
    state.episode_index = 0
    state.has_next = True
    service._next_candidates['series'] = (state, {'provider': 'test', 'id': 'episode2'})
    entered, cancelled = asyncio.Event(), asyncio.Event()
    async def resolve(*args):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    service._online_service = SimpleNamespace(resolve_stream=resolve)
    service._handle_progress('series', 'time-pos', 520)
    await asyncio.wait_for(entered.wait(), 1)
    if cancel == 'stop':
        service.stop()
    elif cancel == 'change':
        service._begin_launch()
    elif cancel == 'disable':
        service.set_auto_next(False)
    elif cancel == 'buffering':
        service._handle_progress('series', 'paused-for-cache', True)
    else:
        await service.stop_all()
    await asyncio.wait_for(cancelled.wait(), 1)
    assert service._prepared_next is None


@pytest.mark.asyncio
async def test_no_prepare_when_disabled_paused_buffering_or_last_episode():
    service, state, _, ts = player()
    service.loop = asyncio.get_running_loop()
    state.timecode = 520
    state.has_next = False
    service._maybe_prepare_next('series', state)
    state.has_next = True
    for attr in ('is_paused', 'is_buffering'):
        setattr(state, attr, True)
        service._maybe_prepare_next('series', state)
        setattr(state, attr, False)
    service.set_auto_next(False)
    service._maybe_prepare_next('series', state)
    await drain()
    assert service._preparation is None
    ts.stream_url.assert_not_called()


@pytest.mark.asyncio
async def test_autoplay_only_at_eof_and_once_for_duplicate_events(monkeypatch):
    monkeypatch.setattr("backend.services.continuation.COUNTDOWN_INTERVAL", 0)
    service, _, _, _ = player()
    await service._refresh_next_available("series")
    service.loop = asyncio.get_running_loop()
    service.play_next_file = AsyncMock(return_value=False)
    service._handle_progress('series', 'time-pos', 550)
    service._handle_progress('series', 'time-pos', 599)
    await drain()
    service.play_next_file.assert_not_awaited()
    service._handle_progress('series', 'eof-reached', True)
    service._handle_end('series', 'eof')
    await drain()
    service._handle_end('series', 'eof')
    await drain()
    service.play_next_file.assert_awaited_once_with('series', 1)


@pytest.mark.asyncio
async def test_manual_launch_invalidates_next_file_lookup_in_flight():
    service, _, _, ts = player()
    entered, release = asyncio.Event(), asyncio.Event()
    async def files(*args):
        entered.set()
        await release.wait()
        return [{'id': 1, 'name': 'S01E01'}, {'id': 5, 'name': 'S01E02'}]
    ts.torrent_video_files.side_effect = files
    service.launch = AsyncMock()
    pending = asyncio.create_task(service.play_next_file('series', 1))
    await entered.wait()
    service._begin_launch()
    release.set()
    assert not await pending
    service.launch.assert_not_awaited()


@pytest.mark.asyncio
async def test_prepared_online_source_is_reused_and_failed_preparation_falls_back():
    for fail in (False, True):
        service, state, _, _ = player()
        service.loop = asyncio.get_running_loop()
        state.is_online = True
        state.playlist_id = 'playlist'
        state.episode_index = 0
        playlist = SimpleNamespace(items=[SimpleNamespace(provider='test', id='one'),
                                          SimpleNamespace(provider='test', id='two')])
        service._online_repo = SimpleNamespace(get_playlist=MagicMock(return_value=playlist))
        info = SimpleNamespace(url='https://test.invalid/next', title='Next', thumbnail='', duration=600)
        resolver = AsyncMock(return_value=info)
        service._online_service = SimpleNamespace(resolve_stream=resolver)
        await service._refresh_next_available('series')
        if fail:
            resolver.side_effect = OSError('temporary resolver failure')
        service._handle_progress('series', 'time-pos', 520)
        await drain()
        assert bool(service._prepared_next) is not fail
        resolver.reset_mock()
        resolver.side_effect = None
        service.launch_online = AsyncMock(return_value='launched')
        assert await service.play_next_online('playlist', 0)
        assert service.launch_online.await_args.kwargs['stream_url'] == info.url
        assert resolver.await_count == int(fail)


@pytest.mark.asyncio
async def test_duplicate_next_requests_cannot_skip_an_episode():
    service, state, _, _ = player()
    async def launch(command, **kwargs):
        await asyncio.sleep(0.01)
        service._begin_launch()
        state.file_id = command.file_id
        return 'launched'
    service.launch = AsyncMock(side_effect=launch)
    result = await asyncio.gather(service.play_next_file('series', 1), service.play_next_file('series', 1))
    assert result == [True, False]
    service.launch.assert_awaited_once()


def test_auto_next_setting_is_persisted_without_ui_panel():
    from backend.services.settings import SettingsService

    service = SettingsService(MagicMock(), lambda: 'http://localhost')
    prefs = {'auto_next': True}
    service.load_settings = MagicMock(return_value=prefs)
    service.save_settings = MagicMock()
    service.update_settings({'auto_next': False})
    assert service.save_settings.call_args.args[0]['auto_next'] is False
    assert service.get_settings()['auto_next'] is False
