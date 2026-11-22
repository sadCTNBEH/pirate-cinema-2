import asyncio
import logging
import re
from functools import lru_cache
from typing import Annotated, Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from backend.core.settings import (
    get_torznab_config,
    load_settings,
)
from backend.exceptions import (
    AppException,
)
from backend.infrastructure.catalog import cinemeta
from backend.infrastructure.mpv.controller import MPVController
from backend.infrastructure.search import RuTorTorrServerProvider
from backend.infrastructure.torrserver import client as torrserver
from backend.infrastructure.torrserver.client import (
    FakeTorrentEngine as FakeTorrentEngine,
    ITorrentEngine as ITorrentEngine,
    TorrentEngine,
    TorrServerAdapter,
)
from backend.repositories.audio import AudioRepository
from backend.repositories.collections import CollectionRepository
from backend.repositories.db import Database
from backend.repositories.history import HistoryRepository
from backend.repositories.library import LibraryRepository
from backend.repositories.metadata import MetadataRepository
from backend.repositories.online import OnlineRepository
from backend.repositories.playback import PlaybackRepository
from backend.services.collections import CollectionService
from backend.services.diagnostics import DiagnosticsService, default_error_buffer
from backend.services.history import HistoryService
from backend.services.library import LibraryService
from backend.services.magnet import MagnetService
from backend.services.metadata import MetadataService
from backend.services.mobile import MobileAccess, mobile_access
from backend.services.online.online_history import OnlineHistoryService
from backend.services.online.playlist_service import PlaylistService
from backend.services.online.service import OnlineService
from backend.services.playback import PlaybackService
from backend.services.progress import SeasonProgressService
from backend.services.remote import get_remote_info
from backend.services.search import SearchService
from backend.services.settings import SettingsService
from backend.services.updater import UpdaterService

logger = logging.getLogger(__name__)

# ─── Error Sanitization & Unified Domain Handlers ───

# Match Windows drives (C:\... or C:/...), UNC paths (\\...), and Unix absolute paths (/home/..., /var/..., etc.)
_PATH_PATTERNS = [
    re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[/\\][^\s\"':<>\n\r\t]+"),
    re.compile(r"\\\\[^\s\"':<>\n\r\t]+"),
    re.compile(
        r"(?<!https://)(?<!http://)(?<!/api)/(?:home|Users|var|tmp|etc|usr|opt|root|data|app|srv|bin|sbin|lib|dev|proc|sys|private|mnt|media)/[^\s\"':<>\n\r\t]+"
    ),
]


def sanitize_error_message(message: str | None) -> str:
    """Sanitize error messages to remove internal file system paths and stack traces."""
    if not message:
        return "Internal error"
    sanitized = str(message)
    for pattern in _PATH_PATTERNS:
        sanitized = pattern.sub("<path>", sanitized)
    # Strip raw Python traceback traces if present in message string
    if "Traceback (most recent call last):" in sanitized:
        sanitized = (
            sanitized.split("Traceback (most recent call last):")[0].strip()
            or "Internal server error"
        )
    return sanitized


def map_exception_to_http(exc: Exception) -> tuple[int, str]:
    """Map internal domain and Python exceptions to safe (status_code, detail) tuples without leaking paths or traces."""
    if isinstance(exc, AppException):
        status_code = getattr(exc, "status_code", 400)
        message = getattr(exc, "message", str(exc))
        return status_code, sanitize_error_message(message)

    if isinstance(exc, HTTPException):
        detail = getattr(exc, "detail", str(exc))
        return exc.status_code, sanitize_error_message(str(detail))

    if isinstance(exc, FileNotFoundError):
        return 404, sanitize_error_message("Requested file or resource was not found")

    if isinstance(exc, PermissionError):
        return 403, "Access to resource is forbidden"

    if isinstance(exc, (ValueError, KeyError)):
        return 400, sanitize_error_message(str(exc))

    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return 504, "Operation timed out"

    logger.exception("Unhandled internal exception: %s", exc)
    return 500, "Internal server error"


async def domain_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI exception handler that converts internal domain errors to safe HTTP responses."""
    status_code, detail = map_exception_to_http(exc)
    if status_code >= 500:
        logger.error("Domain/Internal error [%s]: %s", status_code, exc, exc_info=True)
    else:
        logger.warning("Domain exception [%s]: %s", status_code, detail)
    return JSONResponse(status_code=status_code, content={"detail": detail})


def register_exception_handlers(app: FastAPI) -> None:
    """Register uniform domain exception handlers on a FastAPI application."""
    app.add_exception_handler(AppException, domain_exception_handler)
    app.add_exception_handler(FileNotFoundError, domain_exception_handler)
    app.add_exception_handler(PermissionError, domain_exception_handler)
    app.add_exception_handler(ValueError, domain_exception_handler)
    app.add_exception_handler(KeyError, domain_exception_handler)
    app.add_exception_handler(Exception, domain_exception_handler)


def safe_execute(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Execute a callable and convert internal domain errors to safe HTTPExceptions."""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        status_code, detail = map_exception_to_http(e)
        raise HTTPException(status_code=status_code, detail=detail) from None


async def safe_async_execute(coro_or_func: Any, *args: Any, **kwargs: Any) -> Any:
    """Execute an async callable and convert internal domain errors to safe HTTPExceptions."""
    try:
        if callable(coro_or_func):
            res = coro_or_func(*args, **kwargs)
            if asyncio.iscoroutine(res):
                return await res
            return res
        return await coro_or_func
    except Exception as e:
        status_code, detail = map_exception_to_http(e)
        raise HTTPException(status_code=status_code, detail=detail) from None


# ─── Settings & Infra Helpers ───


def get_torrserver_url() -> str:
    return load_settings()["torrserver_endpoint"]


def get_torrserver_url_provider() -> Callable[[], str]:
    return get_torrserver_url


def get_torrserver_client() -> Any:
    return torrserver


def get_torrent_engine(
    client: Annotated[Any, Depends(get_torrserver_client)] = torrserver,
    settings_provider: Annotated[Any, Depends(get_torrserver_url_provider)] = get_torrserver_url,
) -> TorrentEngine:
    if isinstance(client, TorrentEngine):
        return client
    return TorrServerAdapter(base_url=settings_provider, client=client)


def get_torznab_config_provider() -> Callable[..., Any]:
    return get_torznab_config


def get_mpv_controller_factory() -> Callable[[], MPVController]:
    return MPVController


def get_window_api() -> Any:
    from backend.gui import window_api

    return window_api


# ─── Repositories Providers ───


@lru_cache
def get_database() -> Database:
    db = Database()
    db.init_db()
    return db


def get_library_repo(
    db: Annotated[Database, Depends(get_database)],
) -> LibraryRepository:
    return LibraryRepository(db=db)


def get_playback_repo(
    db: Annotated[Database, Depends(get_database)],
) -> PlaybackRepository:
    return PlaybackRepository(db=db)


def get_history_repo(
    db: Annotated[Database, Depends(get_database)],
) -> HistoryRepository:
    return HistoryRepository(db=db)


def get_metadata_repo(
    db: Annotated[Database, Depends(get_database)],
) -> MetadataRepository:
    return MetadataRepository(db=db)


def get_audio_repo(
    db: Annotated[Database, Depends(get_database)],
) -> AudioRepository:
    return AudioRepository(db=db)


def get_collection_repo(
    db: Annotated[Database, Depends(get_database)],
) -> CollectionRepository:
    return CollectionRepository(db=db)


def get_online_repo(
    db: Annotated[Database, Depends(get_database)],
) -> OnlineRepository:
    return OnlineRepository(db=db)


# ─── Services Providers ───


@lru_cache
def get_metadata_service() -> MetadataService:
    """Application-scoped singleton provider for MetadataService to track active background tasks."""
    db = get_database()
    return MetadataService(
        metadata_repo=MetadataRepository(db=db),
        library_repo=LibraryRepository(db=db),
        catalog_client=cinemeta,
    )


def get_library_service(
    library_repo: Annotated[LibraryRepository, Depends(get_library_repo)],
    metadata_service: Annotated[MetadataService, Depends(get_metadata_service)],
    torrserver_client: Annotated[Any, Depends(get_torrserver_client)] = torrserver,
    settings_provider: Annotated[Any, Depends(get_torrserver_url_provider)] = get_torrserver_url,
) -> LibraryService:
    return LibraryService(
        library_repo=library_repo,
        torrserver_client=torrserver_client,
        settings_provider=settings_provider,
        metadata_service=metadata_service,
    )


def get_collection_service(
    collection_repo: Annotated[CollectionRepository, Depends(get_collection_repo)],
) -> CollectionService:
    return CollectionService(collection_repo=collection_repo)


def get_progress_service(
    history_repo: Annotated[HistoryRepository, Depends(get_history_repo)],
    metadata_repo: Annotated[MetadataRepository, Depends(get_metadata_repo)],
    library_repo: Annotated[LibraryRepository, Depends(get_library_repo)],
    metadata_service: Annotated[MetadataService, Depends(get_metadata_service)],
    torrserver_client: Annotated[Any, Depends(get_torrserver_client)] = torrserver,
    settings_provider: Annotated[Any, Depends(get_torrserver_url_provider)] = get_torrserver_url,
) -> SeasonProgressService:
    return SeasonProgressService(
        history_repo=history_repo,
        metadata_repo=metadata_repo,
        library_repo=library_repo,
        torrserver_client=torrserver_client,
        settings_provider=settings_provider,
        metadata_service=metadata_service,
    )


def get_history_service(
    history_repo: Annotated[HistoryRepository, Depends(get_history_repo)],
    progress_service: Annotated[SeasonProgressService, Depends(get_progress_service)],
) -> HistoryService:
    return HistoryService(history_repo=history_repo, progress_service=progress_service)


@lru_cache
def get_online_service() -> OnlineService:
    return OnlineService()


def get_playlist_service(
    online_repo: Annotated[OnlineRepository, Depends(get_online_repo)],
) -> PlaylistService:
    return PlaylistService(repo=online_repo)


def get_online_history_service(
    online_repo: Annotated[OnlineRepository, Depends(get_online_repo)],
) -> OnlineHistoryService:
    return OnlineHistoryService(repo=online_repo)


def get_mobile_service() -> MobileAccess:
    """Provider for MobileAccess singleton instance."""
    return mobile_access


get_mobile_access = get_mobile_service


class RemoteService:
    """Service provider for Web Remote operations."""

    def get_info(self, port: int | None = None) -> dict[str, Any]:
        return get_remote_info(port)


def get_remote_service() -> RemoteService:
    return RemoteService()


def get_magnet_service(
    metadata_service: Annotated[MetadataService, Depends(get_metadata_service)],
    library_repo: Annotated[LibraryRepository, Depends(get_library_repo)],
    torrserver_client: Annotated[Any, Depends(get_torrserver_client)] = torrserver,
    settings_provider: Annotated[Any, Depends(get_torrserver_url_provider)] = get_torrserver_url,
    torrent_engine: Annotated[TorrentEngine, Depends(get_torrent_engine)] = None,
) -> MagnetService:
    engine = (
        torrent_engine
        if torrent_engine is not None
        else (
            torrserver_client
            if isinstance(torrserver_client, TorrentEngine)
            else TorrServerAdapter(base_url=settings_provider, client=torrserver_client)
        )
    )
    return MagnetService(
        engine=engine,
        torrserver_client=torrserver_client,
        settings_provider=settings_provider,
        metadata_service=metadata_service,
        library_repo=library_repo,
    )


def get_search_service(
    torrserver_client: Annotated[Any, Depends(get_torrserver_client)] = torrserver,
    settings_provider: Annotated[Any, Depends(get_torrserver_url_provider)] = get_torrserver_url,
    torznab_config: Annotated[Any, Depends(get_torznab_config_provider)] = get_torznab_config,
) -> SearchService:
    rutor_provider = RuTorTorrServerProvider(
        torrserver_client=torrserver_client,
        base_url_provider=settings_provider,
    )
    return SearchService(
        providers=[rutor_provider],
        torrserver_client=torrserver_client,
        settings_provider=settings_provider,
        torznab_config_provider=torznab_config,
    )


def create_playback_service(
    playback_repo: Annotated[PlaybackRepository, Depends(get_playback_repo)],
    history_repo: Annotated[HistoryRepository, Depends(get_history_repo)],
    metadata_repo: Annotated[MetadataRepository, Depends(get_metadata_repo)],
    library_repo: Annotated[LibraryRepository, Depends(get_library_repo)],
    online_repo: Annotated[OnlineRepository, Depends(get_online_repo)],
    metadata_service: Annotated[MetadataService, Depends(get_metadata_service)],
    online_service: Annotated[OnlineService, Depends(get_online_service)],
    search_service: Annotated[SearchService, Depends(get_search_service)],
    magnet_service: Annotated[MagnetService, Depends(get_magnet_service)],
    torrserver_client: Annotated[Any, Depends(get_torrserver_client)] = torrserver,
    settings_provider: Annotated[Any, Depends(get_torrserver_url_provider)] = get_torrserver_url,
    mpv_controller_factory: Annotated[Any, Depends(get_mpv_controller_factory)] = MPVController,
) -> PlaybackService:
    """Factory to create a new PlaybackService instance with injected dependencies."""
    return PlaybackService(
        playback_repo=playback_repo,
        history_repo=history_repo,
        metadata_repo=metadata_repo,
        mpv_controller_factory=mpv_controller_factory,
        torrserver_client=torrserver_client,
        settings_provider=settings_provider,
        library_repo=library_repo,
        metadata_service=metadata_service,
        online_repo=online_repo,
        online_service=online_service,
        search_service=search_service,
        magnet_service=magnet_service,
    )


@lru_cache
def _get_default_playback_service() -> PlaybackService:
    db = get_database()
    online_repo = OnlineRepository(db=db)
    return PlaybackService(
        playback_repo=PlaybackRepository(db=db),
        history_repo=HistoryRepository(db=db),
        metadata_repo=MetadataRepository(db=db),
        mpv_controller_factory=MPVController,
        torrserver_client=torrserver,
        settings_provider=get_torrserver_url,
        library_repo=LibraryRepository(db=db),
        metadata_service=get_metadata_service(),
        online_repo=online_repo,
        online_service=get_online_service(),
        search_service=get_search_service(),
        magnet_service=MagnetService(
            torrserver_client=torrserver,
            settings_provider=get_torrserver_url,
            metadata_service=None,
            library_repo=LibraryRepository(db=db),
        ),
    )


def get_playback_service() -> PlaybackService:
    """Application-scoped singleton provider for PlaybackService.

    Maintains active MPV player processes and IPC socket connections across HTTP requests.
    Can be overridden via FastAPI app.dependency_overrides[get_playback_service].
    """
    return _get_default_playback_service()


def get_settings_service(
    torrserver_client: Annotated[Any, Depends(get_torrserver_client)] = torrserver,
    settings_provider: Annotated[Any, Depends(get_torrserver_url_provider)] = get_torrserver_url,
) -> SettingsService:
    return SettingsService(
        torrserver_client=torrserver_client,
        settings_provider=settings_provider,
    )


def get_diagnostics_service(
    db: Annotated[Database, Depends(get_database)],
    torrserver_client: Annotated[Any, Depends(get_torrserver_client)] = torrserver,
    settings_provider: Annotated[Any, Depends(get_torrserver_url_provider)] = get_torrserver_url,
    playback_service: Annotated[PlaybackService, Depends(get_playback_service)] = None,
) -> DiagnosticsService:
    ps = playback_service if playback_service is not None else get_playback_service()
    return DiagnosticsService(
        db=db,
        error_buffer=default_error_buffer,
        torrserver_url_provider=settings_provider,
        torrserver_client=torrserver_client,
        playback_status_provider=lambda: ps.get_health(),
    )


@lru_cache
def get_updater_service() -> UpdaterService:
    return UpdaterService()
