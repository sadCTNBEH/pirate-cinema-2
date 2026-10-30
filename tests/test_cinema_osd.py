"""OSD commands must use existing service actions and keep the IPC reader free."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.infrastructure.mpv import controller as controller_module
from backend.infrastructure.mpv.controller import MPVController
from backend.models.playback import PlaybackState
from backend.services.playback import PlaybackService


@pytest.mark.parametrize('platform_name', ['nt', 'posix'])
def test_osd_messages_do_not_change_state_or_stop_ipc_on_malformed_json(monkeypatch, mpv_ipc_stream, platform_name):
    controller = MPVController()
    controller.is_running = True
    events = [
        {"event": "client-message", "args": ["cinema-action", "broken"]},
        {"event": "client-message", "args": ["cinema-action", '{"not":"command"}']},
        {"event": "client-message", "args": ["cinema-action", '["cycle","pause"]']},
        {"event": "property-change", "name": "pause", "data": True},
    ]
    stream = mpv_ipc_stream(('\n'.join(json.dumps(e) for e in events)+'\n').encode())
    controller.pipe = stream
    # Exercise both reader branches on every runner without changing global os.name.
    monkeypatch.setattr(controller_module, 'os', SimpleNamespace(name=platform_name))
    controller.stop = MagicMock()
    calls = []
    controller.on_progress = lambda name, value: calls.append((name, value))
    controller._reader_loop()
    assert calls == [("cinema-action", ["cycle", "pause"]), ("pause", True), ("flush", True)]
    assert len(stream.readers) == (0 if platform_name == 'nt' else 1)
    assert all(reader.closed for reader in stream.readers)
    controller.stop.assert_called_once_with()


def service_fixture():
    controller = MagicMock(is_running=True)
    service = PlaybackService(MagicMock(), MagicMock(), MagicMock(), lambda: controller,
                              MagicMock(), lambda: '')
    service.controllers['hash'] = controller
    service.active_states['hash'] = PlaybackState(hash='hash', file_id=4, has_next=True)
    return service, controller


def test_osd_uses_shared_actions_and_rejects_stale_session(monkeypatch):
    service, controller = service_fixture()
    service.set_fullscreen = MagicMock()
    service.play_next_file = AsyncMock(return_value=True)

    async def run():
        await service._handle_osd_action('hash', ['seek', 35, 'absolute'])
        controller.send_command.assert_called_once_with(['seek', 35, 'absolute'])
        await service._handle_osd_action('hash', ['cinema', 'fullscreen'])
        service.set_fullscreen.assert_called_once_with()
        await service._handle_osd_action('hash', ['cinema', 'next'])
        service.play_next_file.assert_awaited_once_with('hash', 4)
        for command in (['set_property', 'aid', 2], ['set_property', 'sid', 'no'],
                        ['set_property', 'volume', 47], ['cycle', 'mute']):
            await service._handle_osd_action('hash', command)
            controller.send_command.assert_called_with(command)
        previous_calls = controller.send_command.call_count
        await service._handle_osd_action('stale', ['cycle', 'pause'])
        assert controller.send_command.call_count == previous_calls
        await service._handle_osd_action('hash', ['run', 'unrelated'])
        assert controller.send_command.call_count == previous_calls

    asyncio.run(run())


def test_osd_reader_schedules_command_once_on_service_loop():
    service, controller = service_fixture()

    async def run():
        service.loop = asyncio.get_running_loop()
        await asyncio.to_thread(service._handle_progress, 'hash', 'cinema-action', ['cycle', 'pause'])
        # Drain queued work without tying the reader to the command's completion.
        for _ in range(10):
            if controller.send_command.called:
                break
            await asyncio.sleep(0.01)
        controller.send_command.assert_called_once_with(['cycle', 'pause'])

    asyncio.run(run())


def test_next_availability_tracks_current_file_and_hides_last_episode():
    service, controller = service_fixture()
    service._torrserver.torrent_video_files = AsyncMock(return_value=[
        {'id': 4, 'name': 'S01E01.mkv'}, {'id': 7, 'name': 'S01E02.mkv'},
    ])

    async def run():
        await service._refresh_next_available('hash')
        assert service.active_states['hash'].has_next is True
        controller.send_command.assert_called_with(['script-message', 'cinema-next', 'yes'])
        service.active_states['hash'].file_id = 7
        await service._refresh_next_available('hash')
        assert service.active_states['hash'].has_next is False
        controller.send_command.assert_called_with(['script-message', 'cinema-next', 'no'])
        service.play_next_file = AsyncMock()
        await service._handle_osd_action('hash', ['cinema', 'next'])
        service.play_next_file.assert_not_awaited()

    asyncio.run(run())


def test_distinct_rapid_osd_clicks_are_not_discarded_as_duplicate_commands():
    service, controller = service_fixture()

    async def run():
        for command in (['cycle', 'pause'], ['cycle', 'mute']):
            controller.send_command.reset_mock()
            await service._handle_osd_action('hash', command)
            await service._handle_osd_action('hash', command)
            assert controller.send_command.call_count == 2

    asyncio.run(run())


def test_manual_next_without_successor_keeps_torrent_and_online_player_open():
    service, controller = service_fixture()
    service._torrserver.torrent_video_files = AsyncMock(return_value=[{'id':4,'name':'S01E01.mkv'}])
    service._online_repo = MagicMock()
    service._online_repo.get_playlist.return_value = SimpleNamespace(items=[SimpleNamespace()])
    service._online_service = MagicMock()
    service.stop = MagicMock()

    async def run():
        assert await service.play_next_file('hash', 4) is False
        service.stop.assert_not_called()
        assert await service.play_next_online('playlist', 0) is False
        service.stop.assert_not_called()
        state = service.active_states['hash']
        state.is_online, state.playlist_id, state.episode_index = True, 'playlist', 0
        await service._refresh_next_available('hash')
        assert state.has_next is False
        controller.send_command.assert_called_with(['script-message', 'cinema-next', 'no'])
        assert await service.play_next_online('playlist', 0, stop_at_end=True) is False
        service.stop.assert_called_once()

    asyncio.run(run())


def test_embedded_fullscreen_round_trip_never_switches_mpv_child_to_fullscreen(monkeypatch):
    from backend.gui import window_api

    service, controller = service_fixture()
    controller.is_embedded = True
    monkeypatch.setattr(window_api, 'set_fullscreen', MagicMock(side_effect=lambda target: target))
    for target in (True, False, True, False):
        assert service.set_fullscreen(target) is target
    commands = [call.args[0] for call in controller.send_command.call_args_list]
    assert not any(command[:2] == ['set_property', 'fullscreen'] for command in commands)
    assert commands.count(['script-message', 'cinema-fullscreen', 'yes']) == 2
    controller.send_command.reset_mock()
    window_api.set_fullscreen.reset_mock()
    # Initial/stale false events from the child must not collapse fullscreen host.
    service._handle_progress('hash', 'fullscreen', False)
    window_api.set_fullscreen.assert_not_called()
    controller.send_command.assert_not_called()


def test_external_mpv_retains_its_native_fullscreen(monkeypatch):
    from backend.gui import window_api

    service, controller = service_fixture()
    controller.is_embedded = False
    monkeypatch.setattr(window_api, 'set_fullscreen', MagicMock(return_value=True))
    assert service.set_fullscreen(True) is True
    controller.send_command.assert_called_once_with(['set_property', 'fullscreen', True])


def test_frame_step_osd_action_allowed_when_paused_and_loaded():
    service, controller = service_fixture()
    state = service.active_states['hash']
    state.is_paused = True
    state.is_ready = True
    state.duration = 120
    state.timecode = 15

    async def run():
        await service._handle_osd_action('hash', ['frame-step'])
        controller.send_command.assert_called_once_with(['frame-step'])
        controller.send_command.reset_mock()

        await service._handle_osd_action('hash', ['frame-back-step'])
        controller.send_command.assert_called_once_with(['frame-back-step'])

    asyncio.run(run())


def test_frame_step_osd_action_rejected_when_playing():
    service, controller = service_fixture()
    state = service.active_states['hash']
    state.is_paused = False
    state.is_ready = True
    state.duration = 120

    async def run():
        await service._handle_osd_action('hash', ['frame-step'])
        await service._handle_osd_action('hash', ['frame-back-step'])
        controller.send_command.assert_not_called()

    asyncio.run(run())


def test_frame_step_osd_action_rejected_when_not_loaded():
    service, controller = service_fixture()
    state = service.active_states['hash']
    state.is_paused = True
    state.is_ready = False
    state.duration = 0

    async def run():
        await service._handle_osd_action('hash', ['frame-step'])
        await service._handle_osd_action('hash', ['frame-back-step'])
        controller.send_command.assert_not_called()

    asyncio.run(run())


def test_frame_step_osd_action_never_sent_to_dlna_chromecast():
    service, controller = service_fixture()
    state = service.active_states['hash']
    state.is_paused = True
    state.is_ready = True
    state.duration = 120
    service.tv.state = MagicMock()
    service.tv.command = AsyncMock()

    async def run():
        await service._handle_osd_action('hash', ['frame-step'])
        await service._handle_osd_action('hash', ['frame-back-step'])
        controller.send_command.assert_not_called()
        service.tv.command.assert_not_called()

    asyncio.run(run())


def test_frame_step_whitelist_and_tampered_commands_rejected():
    service, controller = service_fixture()
    state = service.active_states['hash']
    state.is_paused = True
    state.is_ready = True
    state.duration = 120

    async def run():
        for bad_cmd in (
            ['frame-step', '--flag'],
            ['frame-step', 'extra'],
            ['frame-back-step', 1],
            ['frame_step'],
            ['FRAME-STEP'],
            ['frame-step', 'evil;'],
            ['frame-forward'],
        ):
            await service._handle_osd_action('hash', bad_cmd)
            controller.send_command.assert_not_called()

        await service._handle_osd_action('unknown_hash', ['frame-step'])
        controller.send_command.assert_not_called()

    asyncio.run(run())


def test_frame_step_boundary_cases_at_start_and_end_of_video():
    service, controller = service_fixture()
    state = service.active_states['hash']
    state.is_paused = True
    state.is_ready = True
    state.duration = 120

    async def run():
        # At start of video (timecode = 0)
        state.timecode = 0
        await service._handle_osd_action('hash', ['frame-back-step'])
        controller.send_command.assert_called_with(['frame-back-step'])
        assert state.is_paused is True
        controller.send_command.reset_mock()

        # At end of video (timecode = duration)
        state.timecode = 120
        await service._handle_osd_action('hash', ['frame-step'])
        controller.send_command.assert_called_with(['frame-step'])
        assert state.is_paused is True

    asyncio.run(run())


def test_frame_step_targets_only_matching_running_controller():
    service, controller = service_fixture()
    state = service.active_states['hash']
    state.is_paused = state.is_ready = True
    other = MagicMock(is_running=True)
    service.controllers['other'] = other

    async def run():
        await service._handle_osd_action('hash', ['frame-step'])
        controller.send_command.assert_called_once_with(['frame-step'])
        other.send_command.assert_not_called()
        controller.send_command.reset_mock()
        controller.is_running = False
        await service._handle_osd_action('hash', ['frame-back-step'])
        controller.send_command.assert_not_called()
        service.controllers.pop('hash')
        await service._handle_osd_action('hash', ['frame-step'])
        other.send_command.assert_not_called()

    asyncio.run(run())


def test_malformed_frame_steps_are_not_forwarded_to_cast():
    service, controller = service_fixture()
    service.tv.state = MagicMock()
    service.tv.command = AsyncMock()

    async def run():
        for command in (['frame-step', 'extra'], ['frame-back-step', 1]):
            await service._handle_osd_action('hash', command)
        service.tv.command.assert_not_awaited()
        controller.send_command.assert_not_called()

    asyncio.run(run())


def test_frame_step_dropped_when_player_is_replaced_before_dispatch(monkeypatch):
    service, controller = service_fixture()
    state = service.active_states['hash']
    state.is_paused = state.is_ready = True

    async def dispatch_after_switch(callback):
        service.active_states['hash'] = PlaybackState(hash='hash', file_id=5, is_paused=True, is_ready=True)
        callback()

    monkeypatch.setattr('backend.services.playback.anyio.to_thread.run_sync', dispatch_after_switch)
    asyncio.run(service._handle_osd_action('hash', ['frame-step']))
    controller.send_command.assert_not_called()
