from types import SimpleNamespace
from unittest.mock import MagicMock, call

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import deps
from backend.api.routers.settings import settings_router
from backend.core.settings import user
from backend.infrastructure.mpv.controller import MPVController
from backend.services.playback import PlaybackService
from backend.services.settings import SettingsService


def test_subtitle_settings_round_trip_and_live_apply(tmp_path, monkeypatch):
    monkeypatch.setattr(user, 'settings_path', lambda: tmp_path / 'settings.json')
    service = SettingsService(MagicMock(), lambda: '')
    player = PlaybackService(MagicMock(), MagicMock(), MagicMock(), MPVController, MagicMock(), lambda: '')
    controller = MPVController()
    controller.is_running = True
    controller.send_command = MagicMock()
    player.controllers['local'] = controller
    monkeypatch.setattr(deps, 'get_playback_service', lambda: player)
    app = FastAPI()
    app.include_router(settings_router)
    app.dependency_overrides[deps.get_settings_service] = lambda: service

    with TestClient(app) as client:
        defaults = client.get('/api/settings').json()['subtitle_settings']
        assert defaults['speed'] == 1 and defaults['position'] == 100
        style = {
            'font': 'DejaVu Sans', 'font_size': 46, 'color': '#eedd77',
            'border_size': 3, 'border_color': '#332211', 'shadow_offset': 2, 'position': 88,
        }
        assert client.post('/api/settings', json={'subtitle_settings': style}).status_code == 200
        factor = (24000 / 1001) / 25
        assert client.post('/api/settings', json={'subtitle_settings': {'speed': factor}}).status_code == 200
        expected = style | {'speed': factor}
        assert client.get('/api/settings').json()['subtitle_settings'] == expected
        for patch in ({'speed': 0}, {'speed': True}, {'position': 110}, {'color': 'red'}, {'font': '  '}):
            assert client.post('/api/settings', json={'subtitle_settings': patch}).status_code == 422
        assert client.post('/api/settings', json={'seek_step': 15}).status_code == 200
        assert client.get('/api/settings').json()['subtitle_settings'] == expected

    commands = [
        call(['set_property', 'sub-font', 'DejaVu Sans']),
        call(['set_property', 'sub-font-size', 46]),
        call(['set_property', 'sub-color', '#eedd77']),
        call(['set_property', 'sub-border-size', 3]),
        call(['set_property', 'sub-border-color', '#332211']),
        call(['set_property', 'sub-shadow-offset', 2]),
        call(['set_property', 'sub-pos', 88]),
        call(['set_property', 'sub-speed', factor]),
    ]
    controller.send_command.assert_has_calls(commands)
    assert not any(args[0][1] in ('sub-delay', 'audio-delay', 'aid', 'sid')
                   for args, _ in controller.send_command.call_args_list)

    restarted = MPVController()
    restarted.send_command = MagicMock()
    restarted.apply_subtitle_settings()
    restarted.send_command.assert_not_called()
    restarted.is_running = True
    restarted.apply_subtitle_settings()
    assert restarted.send_command.call_args_list == commands


async def test_mpv_menu_persists_only_changed_subtitle_preference(tmp_path, monkeypatch):
    monkeypatch.setattr(user, 'settings_path', lambda: tmp_path / 'settings.json')
    player = PlaybackService(MagicMock(), MagicMock(), MagicMock(), MPVController, MagicMock(), lambda: '')
    player.active_states['local'] = MagicMock()
    player.controllers['local'] = controller = MagicMock()
    player.tv = SimpleNamespace(state=None)
    user.save_settings({'subtitle_settings': {'font_size': 42}})

    for field, value in [('speed', 0.96), ('position', 85)]:
        await player._handle_osd_action('local', ['subtitle-setting', field, value])
        assert user.load_settings()['subtitle_settings'][field] == value
    assert user.load_settings()['subtitle_settings']['font_size'] == 42
    assert controller.apply_subtitle_settings.call_count == 2
    await player._handle_osd_action('local', ['subtitle-setting', 'speed', -1])
    assert user.load_settings()['subtitle_settings']['speed'] == 0.96
    assert controller.apply_subtitle_settings.call_count == 2
