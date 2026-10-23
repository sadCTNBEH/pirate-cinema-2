from unittest.mock import MagicMock

import pytest

from backend.core.settings import user
from backend.infrastructure.torrserver import process


@pytest.fixture
def startup(monkeypatch, tmp_path):
    executable = tmp_path / "vendor" / "torrserver.exe"
    executable.parent.mkdir()
    executable.touch()
    monkeypatch.setattr(process, "_process", None)
    monkeypatch.setattr(process, "_last_error", None)
    monkeypatch.setattr(process, "_probe", MagicMock(side_effect=[False, True]))
    monkeypatch.setattr(process, "_optimize_settings", MagicMock())
    child = MagicMock()
    child.poll.return_value = None
    spawn = MagicMock(return_value=child)
    monkeypatch.setattr(process.subprocess, "Popen", spawn)
    return executable, tmp_path / "user data" / "torrserver", spawn, child


def test_explicit_port_and_writable_data_folder(startup):
    executable, data_dir, spawn, _ = startup
    assert process.connect_or_start(executable=executable, data_dir=data_dir)
    args = spawn.call_args.args[0]
    assert args == [str(executable), "--port", str(process.config.TORRSERVER_PORT),
                    "--ip", "127.0.0.1", "--path", str(data_dir)]
    assert spawn.call_args.kwargs["cwd"] == str(data_dir)
    assert (data_dir / "startup.log").is_file()


def test_crash_includes_real_error_and_log_location(startup):
    executable, data_dir, spawn, child = startup
    child.poll.return_value = 1
    child.returncode = 1

    def fail(*args, **kwargs):
        kwargs["stdout"].write(b"database: permission denied\n")
        kwargs["stdout"].flush()
        return child

    spawn.side_effect = fail
    with pytest.raises(RuntimeError, match="database: permission denied"):
        process.connect_or_start(executable=executable, data_dir=data_dir)
    assert str(data_dir / "startup.log") in process.get_last_error()
    assert "permission denied" in process.get_last_error()


def test_unwritable_folder_does_not_spawn(startup):
    executable, data_dir, spawn, _ = startup
    data_dir.parent.mkdir()
    data_dir.write_text("not a directory")
    with pytest.raises(RuntimeError, match="Cannot write TorrServer data folder"):
        process.connect_or_start(executable=executable, data_dir=data_dir)
    spawn.assert_not_called()


def test_missing_binary_downloads_automatically(startup, monkeypatch):
    executable, data_dir, spawn, _ = startup
    monkeypatch.setattr(process, "bundled_executable", lambda: executable.parent / "missing")
    download = MagicMock(return_value=executable)
    monkeypatch.setattr("backend.infrastructure.downloader.ensure_torrserver_binary", download)
    assert process.connect_or_start(data_dir=data_dir)
    download.assert_called_once_with()
    spawn.assert_called_once()


@pytest.mark.parametrize("url", ["http://127.0.0.1:8090", "http://localhost:8090/"])
def test_migrate_previous_default(monkeypatch, tmp_path, url):
    import json

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"torrserver_url": url}))
    monkeypatch.setattr(user, "settings_path", lambda: path)
    settings = user.load_settings()
    assert settings["torrserver_url"] == user.config.TORRSERVER_DEFAULT_URL
    assert settings["torrserver_endpoint"] == user.config.TORRSERVER_DEFAULT_URL


def test_custom_endpoint_is_preserved(monkeypatch, tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"torrserver_endpoint": "http://192.168.1.5:8090"}')
    monkeypatch.setattr(user, "settings_path", lambda: path)
    assert user.load_settings()["torrserver_url"] == "http://192.168.1.5:8090"


def test_explicit_old_port_can_still_be_saved(monkeypatch, tmp_path):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(user, "settings_path", lambda: path)
    user.save_settings({"torrserver_url": "http://127.0.0.1:8090"})
    assert user.load_settings()["torrserver_url"] == "http://127.0.0.1:8090"
