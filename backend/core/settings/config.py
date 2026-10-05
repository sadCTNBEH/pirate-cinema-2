from typing import ClassVar

from backend.core.settings.base import env, env_float, env_int


class AppConfig:
    # FastAPI + WebView
    APP_HOST: str = env("APP_HOST", "127.0.0.1")
    APP_PORT: int = env_int("APP_PORT", 8000)
    WINDOW_WIDTH: int = env_int("WINDOW_WIDTH", 1280)
    WINDOW_HEIGHT: int = env_int("WINDOW_HEIGHT", 800)
    WINDOW_BG: str = env("WINDOW_BG", "#141414")
    APP_TITLE: str = env("APP_TITLE", "Pirate Cinema")

    # TorrServer
    TORRSERVER_DEFAULT_URL: str = env("TORRSERVER_DEFAULT_URL", "http://127.0.0.1:8090")
    TORRSERVER_PORT: int = env_int("TORRSERVER_PORT", 8090)
    TORRSERVER_START_TIMEOUT: int = env_int("TORRSERVER_START_TIMEOUT", 30)
    TORRSERVER_CONNECTIONS_LIMIT: int = env_int("TORRSERVER_CONNECTIONS_LIMIT", 400)
    TORRSERVER_HTTP_TIMEOUT: float = env_float("TORRSERVER_HTTP_TIMEOUT", 20.0)

    # Catalog
    CINEMETA_URL: str = env("CINEMETA_URL", "https://v3-cinemeta.strem.io")
    USER_AGENT: str = env("USER_AGENT", "PirateCinema/2.0 (local desktop app)")
    CINEMETA_TIMEOUT: float = env_float("CINEMETA_TIMEOUT", 12.0)
    CATALOG_LIMIT: int = env_int("CATALOG_LIMIT", 30)

    # Video
    VIDEO_EXTENSIONS: frozenset[str] = frozenset({
        ".mkv", ".mp4", ".avi", ".mov", ".wmv",
        ".flv", ".webm", ".m4v", ".ts", ".m2ts",
    })

    # Vendor downloads
    TORRSERVER_WIN_URL: str = env(
        "TORRSERVER_WIN_URL",
        "https://github.com/sadCTNBEH/pirate-cinema-2/releases/download/deps/TorrServer-windows-amd64.exe",
    )
    TORRSERVER_LINUX_URL: str = env(
        "TORRSERVER_LINUX_URL",
        "https://github.com/YouROK/TorrServer/releases/download/MatriX.145.2/TorrServer-linux-amd64",
    )
    MPV_WIN_URL: str = env(
        "MPV_WIN_URL",
        "https://github.com/sadCTNBEH/pirate-cinema-2/releases/download/deps/mpv-x86_64-20261004-git-413ff0b1cd.zip",
    )

    # MPV
    MPV_ARGS: ClassVar[list[str]] = [
        "--fs",
        "--force-window=immediate",
        "--idle=once",
        "--keep-open=yes",
        "--msg-level=all=no,cplayer=info",
    ]
    MPV_WIN_EXTRA_ARGS: ClassVar[list[str]] = [
        "--gpu-api=opengl",
        "--gpu-context=win",
        "--hwdec=d3d11va-copy",
    ]
    MPV_PIPE_TIMEOUT: float = env_float("MPV_PIPE_TIMEOUT", 5.0)

    # Updates
    GITHUB_API_URL: str = env("GITHUB_API_URL", "https://api.github.com/repos/sadCTNBEH/pirate-cinema-2/releases/latest")

config = AppConfig()
