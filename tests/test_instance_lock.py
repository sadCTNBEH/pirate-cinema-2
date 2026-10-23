import os
import subprocess
import sys

from backend.infrastructure.instance_lock import instance_lock


def test_lock_blocks_another_process_and_is_released(tmp_path):
    path = tmp_path / "app.lock"
    script = (
        "import sys; from pathlib import Path; "
        "from backend.infrastructure.instance_lock import instance_lock; "
        "lock=instance_lock(Path(sys.argv[1])); lock.__enter__(); lock.__exit__(None,None,None)"
    )
    env = {**os.environ, "PYTHONPATH": os.getcwd()}
    with instance_lock(path):
        blocked = subprocess.run([sys.executable, "-c", script, str(path)],
                                 capture_output=True, env=env, timeout=10, check=False)
        assert blocked.returncode != 0
        assert b"already running" in blocked.stderr
    allowed = subprocess.run([sys.executable, "-c", script, str(path)],
                             capture_output=True, env=env, timeout=10, check=False)
    assert allowed.returncode == 0, allowed.stderr


def test_second_app_does_not_start_backend(monkeypatch, tmp_path):
    import importlib
    from unittest.mock import MagicMock

    main = importlib.import_module("backend.main")
    run = MagicMock()
    stop = MagicMock()
    monkeypatch.setattr(main, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(main, "_run_application", run)
    monkeypatch.setattr(main.torrserver_process, "stop", stop)
    with instance_lock(tmp_path / "app.lock"):
        main.main()
    run.assert_not_called()
    stop.assert_not_called()
