"""Main entry point. Run with: python -m backend.main"""

import logging
import socket
import sys
import threading
import time

import uvicorn

import backend.views  # noqa: F401 - регистрация root-маршрута HTML
from backend.app import app
from backend.core.settings import config
from backend.gui import launch_gui

logger = logging.getLogger(__name__)

server = uvicorn.Server(
    uvicorn.Config(
        app, host=config.APP_HOST, port=config.APP_PORT, log_level="warning"
    )
)


def wait_for_port(host: str, port: int, timeout: float = 10.0) -> bool:
    start = time.time()
    # Если host указан как '0.0.0.0', пингуем локальный интерфейс '127.0.0.1'
    target_host = "127.0.0.1" if host == "0.0.0.0" else host
    while time.time() - start < timeout:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex((target_host, port)) == 0:
                return True
        time.sleep(0.1)
    return False


def main():
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    if not wait_for_port(config.APP_HOST, config.APP_PORT):
        logger.error(
            "Server failed to start on %s:%s", config.APP_HOST, config.APP_PORT
        )
        sys.exit(1)

    launch_gui(server)


if __name__ == "__main__":
    main()
