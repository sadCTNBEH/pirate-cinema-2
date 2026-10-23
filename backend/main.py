"""Main entry point. Run with: python -m backend.main"""

import logging
import sys
import threading
import time

import uvicorn

import backend.views  # noqa: F401 - регистрация root-маршрута HTML
from backend.app import app
from backend.core.settings import BASE_DIR, config, get_data_dir
from backend.gui import launch_gui
from backend.infrastructure.instance_lock import AlreadyRunningError, instance_lock
from backend.infrastructure.torrserver import process as torrserver_process
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


def wait_for_backend(server_thread: threading.Thread, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.started:
            return True
        if not server_thread.is_alive():
            return False
        time.sleep(0.1)
    return False


def main():
    try:
        with instance_lock(get_data_dir() / "app.lock"):
            try:
                _run_application()
            finally:
                server.should_exit = True
                torrserver_process.stop()
    except AlreadyRunningError as e:
        logger.info("%s", e)


def _run_application():
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

    if not wait_for_backend(server_thread, config.TORRSERVER_START_TIMEOUT + 15):
        logger.error(
            "Server failed to start on %s:%s", config.APP_HOST, config.APP_PORT
        )
        if splash:
            splash.close()
        sys.exit(1)

    on_ready = splash.close if splash else None
    launch_gui(
        server,
        on_frontend_ready=on_ready,
        start_minimized=start_minimized,
    )


if __name__ == "__main__":
    main()
