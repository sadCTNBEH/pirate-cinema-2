import socket
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
    monkeypatch.setattr(process, "_active_url", None)
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
    process._probe.side_effect = None
    process._probe.return_value = False

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


def test_startup_retries_early_crash_once_without_resetting_data(startup, monkeypatch):
    executable, data_dir, spawn, healthy = startup
    failed = MagicMock()
    failed.poll.return_value = 1
    failed.returncode = 1
    spawn.side_effect = [failed, healthy]
    monkeypatch.setattr(process, "_probe", MagicMock(side_effect=[False, False, True]))
    data_dir.mkdir(parents=True)
    database = data_dir / "config.db"
    database.write_bytes(b"preserve existing data")
    assert process.connect_or_start(executable=executable, data_dir=data_dir)
    assert spawn.call_count == 2
    assert database.read_bytes() == b"preserve existing data"
    assert "Retrying TorrServer startup" in (data_dir / "startup.log").read_text()


def test_probe_does_not_use_environment_proxy(monkeypatch):
    factory = MagicMock()
    factory.return_value.__enter__.return_value.get.return_value.status_code = 200
    monkeypatch.setattr(process.httpx, "Client", factory)
    assert process._probe("http://127.0.0.1:8091")
    assert factory.call_args.kwargs["trust_env"] is False


def test_local_health_works_with_broken_system_proxy(monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Echo(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"MatriX.145.2")

        def log_message(self, *args):
            pass

    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    with ThreadingHTTPServer(("127.0.0.1", 0), Echo) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            assert process._probe(f"http://127.0.0.1:{server.server_port}")
        finally:
            server.shutdown()
            thread.join(timeout=5)


@pytest.mark.parametrize("url", ["http://127.0.0.1:8090", "http://localhost:8090/"])
def test_existing_local_endpoint_is_preserved(monkeypatch, tmp_path, url):
    import json

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"torrserver_url": url}))
    monkeypatch.setattr(user, "settings_path", lambda: path)
    settings = user.load_settings()
    assert settings["torrserver_url"] == url
    assert settings["torrserver_endpoint"] == url


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


def test_saved_local_port_is_used_to_start(startup, monkeypatch):
    executable, data_dir, spawn, _ = startup
    monkeypatch.setattr(process, "_probe", MagicMock(side_effect=[False, True]))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    assert process.connect_or_start(url, executable, data_dir)
    assert spawn.call_args.args[0][2] == str(port)
    assert process.get_active_url() == url


def test_unresponsive_managed_process_is_not_replaced(startup, monkeypatch):
    executable, data_dir, spawn, child = startup
    monkeypatch.setattr(process, "_process", child)
    monkeypatch.setattr(process, "_probe", lambda url: False)
    with pytest.raises(RuntimeError, match="A second process will not be started"):
        process.connect_or_start(executable=executable, data_dir=data_dir)
    spawn.assert_not_called()
    assert process._process is child


def test_stop_waits_for_killed_process(startup, monkeypatch):
    import subprocess

    _, _, _, child = startup
    monkeypatch.setattr(process, "_process", child)
    child.wait.side_effect = [subprocess.TimeoutExpired("torrserver", 5), 0]
    process.stop()
    child.kill.assert_called_once()
    assert child.wait.call_count == 2
    assert process.get_active_url() is None


def test_remote_endpoint_is_never_started_locally(startup, monkeypatch):
    executable, data_dir, spawn, _ = startup
    monkeypatch.setattr(process, "_probe", lambda url: False)
    with pytest.raises(RuntimeError, match="local HTTP endpoints"):
        process.connect_or_start("http://192.168.1.5:8091", executable, data_dir)
    spawn.assert_not_called()


def test_concurrent_start_requests_spawn_only_once(startup, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    executable, data_dir, spawn, _ = startup
    monkeypatch.setattr(process, "_probe", lambda url: process.is_running())
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(process.connect_or_start, None, executable, data_dir)
                   for _ in range(2)]
        assert all(future.result(timeout=5) for future in futures)
    spawn.assert_called_once()
