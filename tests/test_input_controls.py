from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from backend.api.schemas.settings import SettingsResponse, SettingsUpdate
from backend.core.settings import user
from backend.infrastructure.input_bridge import KEY_CODES, key_payload
from backend.services.settings import SettingsService


def test_hotkeys_persist_through_existing_settings_without_changing_other_preferences(
    tmp_path, monkeypatch
):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(user, "settings_path", lambda: path)
    service = SettingsService(MagicMock(), lambda: "http://localhost")
    service.update_settings(
        {"language": "en", "hotkeys": {"pause": "Ctrl+Shift+KeyK", "mute": ""}}
    )
    assert user.load_settings()["hotkeys"] == {"pause": "Ctrl+Shift+KeyK", "mute": ""}
    assert (
        SettingsResponse(**service.get_settings()).hotkeys["pause"] == "Ctrl+Shift+KeyK"
    )
    service.update_settings({"hotkeys": {}})
    assert user.load_settings()["hotkeys"] == {}
    assert user.load_settings()["language"] == "en"


def test_settings_validate_key_chords_and_keep_backwards_compatibility():
    assert SettingsUpdate(language="ru").hotkeys is None
    assert SettingsUpdate(hotkeys={"pause": "Ctrl+Alt+Shift+KeyK", "mute": ""}).hotkeys
    with pytest.raises(ValidationError):
        SettingsUpdate(hotkeys={"pause": "x" * 81})
    with pytest.raises(ValidationError):
        SettingsUpdate(hotkeys={"pause": "<script>"})


def test_native_keys_use_the_same_browser_codes_and_modifiers():
    assert key_payload(0x46)["code"] == "KeyF"
    assert key_payload(0x25)["code"] == "ArrowLeft"
    assert key_payload(0x20)["code"] == "Space"
    assert key_payload(0x4B, ctrl=True, shift=True, repeat=True) == {
        "code": "KeyK",
        "ctrlKey": True,
        "altKey": False,
        "shiftKey": True,
        "metaKey": False,
        "repeat": True,
    }
    assert len(KEY_CODES) == len(set(KEY_CODES.values()))


def test_native_video_is_hidden_and_webview_refocused_for_controller_dialog(
    monkeypatch,
):
    from backend import gui

    api = gui.WindowApi()
    panel = MagicMock(Visible=True, ContainsFocus=True)
    browser = MagicMock()
    api._viewport_panel = panel
    api._player_visible = True
    monkeypatch.setattr(gui, "_window", MagicMock(native=MagicMock(webview=browser)))
    monkeypatch.setattr(api, "_invoke_ui", lambda fn, sync=False: fn())
    api.set_player_occluded(True)
    assert panel.Visible is False
    browser.Focus.assert_called_once()
    api.set_player_occluded(False)
    assert panel.Visible is True
    panel.BringToFront.assert_called_once()


def test_native_bridge_only_emits_one_shared_keyboard_event(monkeypatch):
    import json

    from backend import gui

    window = MagicMock()
    monkeypatch.setattr(gui, "_window", window)
    payload = key_payload(0x20)
    gui.WindowApi()._emit_input_event("cinema-native-key", payload)
    script = window.evaluate_js.call_args.args[0]
    assert window.evaluate_js.call_count == 1
    assert "cinema-native-key" in script
    assert json.dumps(payload) in script


def test_hotkeys_settings_api_round_trip(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.api import deps
    from backend.app import app

    monkeypatch.setattr(user, "settings_path", lambda: tmp_path / "settings.json")
    service = SettingsService(MagicMock(), lambda: "http://localhost")
    app.dependency_overrides[deps.get_settings_service] = lambda: service
    client = TestClient(app)
    try:
        assert (
            client.post(
                "/api/settings", json={"hotkeys": {"pause": "Shift+KeyK"}}
            ).status_code
            == 200
        )
        assert client.get("/api/settings").json()["hotkeys"] == {"pause": "Shift+KeyK"}
        assert (
            client.post(
                "/api/settings", json={"hotkeys": {"pause": "<invalid>"}}
            ).status_code
            == 422
        )
        assert user.load_settings()["hotkeys"] == {"pause": "Shift+KeyK"}
    finally:
        client.close()
        app.dependency_overrides.pop(deps.get_settings_service, None)
