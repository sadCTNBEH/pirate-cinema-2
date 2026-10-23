"""Main entry point. Run with: python -m backend.main"""

import logging
import socket
import sys
import threading
import time

import uvicorn

import backend.views  # noqa: F401 - регистрация root-маршрута HTML
from backend.app import app
from backend.core.settings import BASE_DIR, config
from backend.gui import launch_gui
from backend.startup_splash import StartupSplash

logger = logging.getLogger(__name__)


class IgnoreInvalidHttpRequestFilter(logging.Filter):
    """Filter out benign TLS handshake / HTTPS upgrade probe warnings from mobile browsers."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "Invalid HTTP request received" not in record.getMessage()


logging.getLogger("uvicorn.error").addFilter(IgnoreInvalidHttpRequestFilter())

server = uvicorn.Server(
    uvicorn.Config(app, host=config.APP_HOST, port=config.APP_PORT, log_level="warning")
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
    start_minimized = any(
        arg in sys.argv for arg in ("--minimized", "--autostart", "--tray")
    )

    splash = None
    if not start_minimized:
        splash_logo = BASE_DIR / "static" / "pirate_cinema_banner_logo.png"
        if not splash_logo.is_file():
            splash_logo = BASE_DIR / "static" / "splash-logo.png"
        if not splash_logo.is_file():
            splash_logo = BASE_DIR / "static" / "logo.png"
            logger.warning("Using fallback startup splash logo: %s", splash_logo)
        splash = StartupSplash(splash_logo)
        splash.start()

    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    if not wait_for_port(config.APP_HOST, config.APP_PORT):
        logger.error(
            "Server failed to start on %s:%s", config.APP_HOST, config.APP_PORT
        )
        if splash:
            splash.close()
        sys.exit(1)

    on_ready = splash.close if splash else None
    if splash:
        # Резервный таймер: закрыть сплэш максимум через 3.0 сек, если UI задерживается
        watchdog = threading.Timer(3.0, splash.close)
        watchdog.daemon = True
        watchdog.start()
    launch_gui(
        server,
        on_frontend_ready=on_ready,
        start_minimized=start_minimized,
    )


if __name__ == "__main__":
    main()
