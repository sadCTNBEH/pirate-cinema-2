import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

logger = logging.getLogger(__name__)


def configure_logging():
    handlers = []
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    try:
        base = os.environ.get("LOCALAPPDATA", str(Path.home())) if sys.platform == "win32" else os.environ.get(
            "XDG_DATA_HOME", str(Path.home() / ".local" / "share")
        )
        folder = Path(base) / "Pirate Cinema"
        folder.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(folder / "startup.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8"))
    except OSError:
        logger.warning("Cannot create startup log", exc_info=True)
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main():
    if "--animego-worker" in sys.argv:
        from backend.services.online.animego_worker import run_worker
        return run_worker() or 0
    configure_logging()
    try:
        if "--smoke-test" in sys.argv or "--smoke-test-mpv" in sys.argv:
            import backend.main  # noqa: F401
            from backend.app import static_dir
            from backend.services.remote import generate_qr_svg
            from backend.services.remote_html import ASSET_TYPES, REMOTE_DIR

            if "<svg" not in generate_qr_svg("http://127.0.0.1:8000/remote"):
                raise RuntimeError("QR generation failed")
            remote_assets = [REMOTE_DIR / name for name in ASSET_TYPES]
            remote_assets.append(static_dir / "vendor" / "hls.light.min.js")
            for asset in remote_assets:
                if not asset.is_file() or asset.stat().st_size == 0:
                    raise RuntimeError(f"Remote asset missing or empty: {asset}")
            if "--smoke-test-mpv" in sys.argv:
                from threading import Event

                from backend.core.settings import config, resolve_mpv_binary
                from backend.infrastructure.mpv.controller import (
                    MPVController,
                    resolve_cinema_lua_path,
                )

                lua_path = resolve_cinema_lua_path()
                if not lua_path or not lua_path.is_file():
                    raise RuntimeError(f"cinema.lua not found or not a regular file: {lua_path}")

                config.MPV_ARGS = [
                    a for a in config.MPV_ARGS if a not in ("--fs", "--force-window=yes")
                ] + ["--vo=null", "--ao=null"]
                controller = MPVController()
                playing = Event()

                def on_progress(name, value):
                    if name == "time-pos" and isinstance(value, (int, float)) and value > 0:
                        playing.set()

                controller.on_progress = on_progress
                try:
                    controller.launch(resolve_mpv_binary(), "av://lavfi:testsrc=duration=2", "Playback self-test")
                    if not playing.wait(5):
                        raise RuntimeError("MPV self-test did not play the test video")
                finally:
                    controller.stop()
            return 0

        from backend.main import main as launch

        launch()
        return 0
    except Exception:
        logger.exception("Pirate Cinema startup failed; see the startup.log in the user data folder")
        return 1

if __name__ == "__main__":
    sys.exit(main())
