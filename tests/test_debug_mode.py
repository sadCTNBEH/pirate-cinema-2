"""Tests for Debug Mode and UI simplification (TASK - Debug Mode)."""
from unittest.mock import MagicMock
from pathlib import Path

from backend.core.settings.user import DEFAULT_SETTINGS, load_settings, save_settings
from backend.services.settings import SettingsService
from backend.infrastructure.mpv.controller import MPVController
from backend.services.playback import PlaybackService
from backend.services.diagnostics import ErrorBuffer


def test_debug_mode_default_is_off():
    """1. Debug Mode is False (OFF) by default."""
    assert DEFAULT_SETTINGS.get("debug_mode") is False
    settings = load_settings()
    assert "debug_mode" in settings
    # If not explicitly set in custom file, default must be False
    assert isinstance(settings["debug_mode"], bool)


def test_debug_mode_saves_and_loads(tmp_path, monkeypatch):
    """2. Debug Mode saves to settings.json and loads back correctly."""
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr("backend.core.settings.user.settings_path", lambda: settings_file)

    # Initial state
    assert load_settings()["debug_mode"] is False

    # Save debug_mode = True
    save_settings({"debug_mode": True})
    assert load_settings()["debug_mode"] is True

    # Save debug_mode = False
    save_settings({"debug_mode": False})
    assert load_settings()["debug_mode"] is False


def test_settings_service_debug_mode(tmp_path, monkeypatch):
    """SettingsService get_settings and update_settings handle debug_mode."""
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr("backend.core.settings.user.settings_path", lambda: settings_file)

    service = SettingsService(torrserver_client=MagicMock(), settings_provider=lambda: "http://127.0.0.1:18765")
    assert service.get_settings()["debug_mode"] is False

    service.update_settings({"debug_mode": True})
    assert service.get_settings()["debug_mode"] is True

    service.update_settings({"debug_mode": False})
    assert service.get_settings()["debug_mode"] is False


def test_debug_mode_switch_notifies_mpv_via_ipc():
    """3 & 4. Switching debug mode forwards IPC command to MPV without restart."""
    controller = MPVController()
    controller.is_running = True
    controller.pipe = MagicMock()
    controller.send_command = MagicMock()

    # Turn ON
    controller.set_debug_mode(True)
    assert controller._debug_mode is True
    controller.send_command.assert_called_with(['script-message', 'cinema-debug-mode', 'yes'])

    # Turn OFF
    controller.set_debug_mode(False)
    assert controller._debug_mode is False
    controller.send_command.assert_called_with(['script-message', 'cinema-debug-mode', 'no'])


def test_playback_service_set_debug_mode():
    """PlaybackService broadcasts debug_mode to all active controllers."""
    controller1 = MagicMock(is_running=True)
    controller2 = MagicMock(is_running=True)
    service = PlaybackService(
        MagicMock(),
        MagicMock(),
        MagicMock(),
        lambda: controller1,
        MagicMock(),
        lambda: "",
    )
    service.controllers["player1"] = controller1
    service.controllers["player2"] = controller2

    service.set_debug_mode(True)
    controller1.set_debug_mode.assert_called_once_with(True)
    controller2.set_debug_mode.assert_called_once_with(True)

    service.set_debug_mode(False)
    controller1.set_debug_mode.assert_called_with(False)
    controller2.set_debug_mode.assert_called_with(False)


def test_dlna_chromecast_not_sent_debug_commands():
    """Debug commands are NOT sent to TV / DLNA / Chromecast sessions."""
    controller = MagicMock(is_running=True)
    service = PlaybackService(
        MagicMock(),
        MagicMock(),
        MagicMock(),
        lambda: controller,
        MagicMock(),
        lambda: "",
    )
    tv_mock = MagicMock()
    service.tv = tv_mock
    service.set_debug_mode(True)

    # TV session must not receive debug command
    assert not tv_mock.send_command.called
    assert not hasattr(tv_mock, 'set_debug_mode') or not tv_mock.set_debug_mode.called


def test_cinema_lua_contains_f035_and_debug_handling():
    """4. cinema.lua implements F-035 video info and responds to cinema-debug-mode."""
    lua_path = Path("backend/infrastructure/mpv/cinema.lua")
    assert lua_path.exists()
    content = lua_path.read_text(encoding="utf-8")

    # Script message registered
    assert "cinema-debug-mode" in content

    # Video info menu logic exists
    assert "video_info_rows" in content
    assert "Информация о видео" in content
    assert "Разрешение" in content
    assert "FPS" in content
    assert "Видеокодек" in content
    assert "Аудиокодек" in content
    assert "Битрейт" in content
    assert "Каналы аудио" in content
    assert "HDR / SDR" in content

    # Item appears only when debug_mode
    assert "if menu=='more' and debug_mode then" in content

    # Turning off debug mode immediately closes video_info menu
    assert "if not debug_mode and menu=='video_info' then" in content


def test_additional_settings_preserved(tmp_path, monkeypatch):
    """8. Additional settings (MPV path, TorrServer URL, categories, Yummy keys) are preserved."""
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr("backend.core.settings.user.settings_path", lambda: settings_file)

    service = SettingsService(torrserver_client=MagicMock(), settings_provider=lambda: "http://127.0.0.1:18765")
    initial_data = {
        "player_path": "C:\\custom\\mpv.exe",
        "torrserver_url": "http://192.168.1.50:8090",
        "torznab_categories": [2000, 5000],
        "yummyanime_public_key": "pub_key_123",
        "yummyanime_private_key": "priv_secret_456",
    }
    service.update_settings(initial_data)

    current = service.get_settings()
    assert current["player_path"] == "C:\\custom\\mpv.exe"
    assert current["torznab"]["categories"] == [2000, 5000]
    assert current["yummyanime_public_key"] == "pub_key_123"
    assert current["yummyanime_private_key"] == "priv_secret_456"

    # Now toggle debug_mode; additional settings must not be reset or modified
    service.update_settings({"debug_mode": True})
    after_toggle = service.get_settings()
    assert after_toggle["debug_mode"] is True
    assert after_toggle["player_path"] == "C:\\custom\\mpv.exe"
    assert after_toggle["torznab"]["categories"] == [2000, 5000]
    assert after_toggle["yummyanime_public_key"] == "pub_key_123"
    assert after_toggle["yummyanime_private_key"] == "priv_secret_456"


def test_backup_and_restore_accessible_without_debug_mode(tmp_path, monkeypatch):
    """9. Backup creation is accessible without debug mode requirement."""
    monkeypatch.setattr("backend.services.settings.get_data_dir", lambda: tmp_path)
    # Create dummy database and settings
    (tmp_path / "settings.json").write_text('{"debug_mode": false}', encoding="utf-8")
    (tmp_path / "database.sqlite").write_text("dummy db", encoding="utf-8")

    service = SettingsService(torrserver_client=MagicMock(), settings_provider=lambda: "")
    zip_path = service.create_backup_zip()
    assert zip_path.exists()
    assert zip_path.suffix == ".zip"
    zip_path.unlink(missing_ok=True)


def test_diagnostics_sanitization():
    """ErrorBuffer sanitizes secrets, tokens, passwords and keys in error reports."""
    buf = ErrorBuffer()
    buf.record("search", "AuthError", "Failed with token=secret123456 and api_key=my_super_key")
    buf.record("http", "RequestError", "Authorization Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9")

    errors = buf.get_errors()
    assert len(errors) == 2
    assert "secret123456" not in errors[0]["message"]
    assert "token=***" in errors[0]["message"]
    assert "api_key=***" in errors[0]["message"]
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in errors[1]["message"]
    assert "Bearer ***" in errors[1]["message"]
