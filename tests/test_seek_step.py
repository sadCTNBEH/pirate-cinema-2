"""F-098: persisted step, live MPV updates and unchanged precise commands."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import deps
from backend.api.routers.settings import settings_router
from backend.api.routers.player import send_player_command
from backend.api.schemas.settings import SettingsResponse
from backend.core.settings import user
from backend.infrastructure.mpv.controller import MPVController
from backend.services.playback import PlaybackService
from backend.services.settings import SettingsService


def playback():
    return PlaybackService(MagicMock(), MagicMock(), MagicMock(), MPVController, MagicMock(), lambda: '')


def test_step_settings_round_trip_and_live_update(tmp_path, monkeypatch):
    path = tmp_path / 'settings.json'
    monkeypatch.setattr(user, 'settings_path', lambda: path)
    service = SettingsService(MagicMock(), lambda: '')
    player = playback()
    controller = MPVController()
    controller.send_command = MagicMock()
    player.controllers['local'] = controller
    monkeypatch.setattr(deps, 'get_playback_service', lambda: player)
    app = FastAPI()
    app.include_router(settings_router)
    app.dependency_overrides[deps.get_settings_service] = lambda: service
    try:
        with TestClient(app) as client:
            assert client.get('/api/settings').json()['seek_step'] == 10
            user.save_settings({'hotkeys': {'seekForward': 'KeyL'}, 'language': 'en'})
            for step in (5, 10, 15, 30, 60):
                assert client.post('/api/settings', json={'seek_step': step}).status_code == 200
                # A fresh service reads the saved file, with no runtime cache.
                fresh = SettingsService(MagicMock(), lambda: '')
                assert SettingsResponse(**fresh.get_settings()).seek_step == step
                assert user.load_settings()['hotkeys'] == {'seekForward': 'KeyL'}
                controller.send_command.assert_called_with(['script-message', 'cinema-seek-step', str(step)])
            assert client.post('/api/settings', json={'seek_step': 20}).status_code == 422
            assert user.load_settings()['seek_step'] == 60
    finally:
        app.dependency_overrides.pop(deps.get_settings_service, None)


@pytest.mark.parametrize('value', [None, '30', 20, [], True])
def test_invalid_saved_step_defaults_to_ten(tmp_path, monkeypatch, value):
    monkeypatch.setattr(user, 'settings_path', lambda: tmp_path / 'settings.json')
    user.save_settings({'seek_step': value})
    assert user.load_settings()['seek_step'] == 10


@pytest.mark.parametrize('step', [5, 10, 15, 30, 60])
async def test_selected_step_is_applied_locally_and_to_casting(tmp_path, monkeypatch, step):
    monkeypatch.setattr(user, 'settings_path', lambda: tmp_path / 'settings.json')
    user.save_settings({'seek_step': step})
    service = playback()
    controller = MagicMock(is_running=True)
    service.controllers['local'] = controller
    service.tv = SimpleNamespace(state=None, command=AsyncMock())
    for direction in (-1, 1):
        service.send_command(['cinema-step', direction])
        controller.send_command.assert_called_with(['seek', direction * step, 'relative'])
    for command in (['seek', 3, 'relative+exact'], ['seek', 42, 'absolute+exact'],
                    ['add', 'chapter', 1], ['frame-step'], ['frame-back-step']):
        service.send_command(command)
        controller.send_command.assert_called_with(command)
    # API casts receive an ordinary seek, never an MPV script command.
    service.tv.state = True
    await send_player_command(['cinema-step', 1], service)
    service.tv.command.assert_awaited_with(['seek', step, 'relative'])
    service.set_seek_step(step)
    service.tv.command.assert_awaited_once()
    # The OSD path uses the same conversion before routing to a receiver.
    service.active_states['local'] = MagicMock()
    await service._handle_osd_action('local', ['cinema-step', -1])
    service.tv.command.assert_awaited_with(['seek', -step, 'relative'])


def test_step_is_resent_after_mpv_script_requests_state(mpv_ipc_stream):
    controller = MPVController()
    controller.send_command = MagicMock()
    controller.set_seek_step(15)
    controller.send_command.reset_mock()
    controller.is_running = True
    controller.pipe = mpv_ipc_stream(b'{"event":"client-message","args":["cinema-segments-request"]}\n')
    controller._reader_loop()
    controller.send_command.assert_any_call(['script-message', 'cinema-seek-step', '15'])
