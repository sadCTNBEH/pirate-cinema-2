from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from backend.core.settings import (
    get_torznab_config,
    load_settings,
)
from backend.infrastructure.catalog import cinemeta
from backend.infrastructure.mpv.controller import MPVController
from backend.infrastructure.search import RuTorTorrServerProvider, TorznabProvider
from backend.infrastructure.torrserver import client as torrserver
from backend.repositories.audio import AudioRepository
from backend.repositories.collections import CollectionRepository
from backend.repositories.db import Database
from backend.repositories.history import HistoryRepository
from backend.repositories.library import LibraryRepository
from backend.repositories.metadata import MetadataRepository
from backend.repositories.online import OnlineRepository
from backend.repositories.playback import PlaybackRepository
from backend.services.collections import CollectionService
from backend.services.history import HistoryService
from backend.services.library import LibraryService
from backend.services.magnet import MagnetService
from backend.services.metadata import MetadataService
from backend.services.online.online_history import OnlineHistoryService
from backend.services.online.playlist_service import PlaylistService
from backend.services.online.service import OnlineService
from backend.services.playback import PlaybackService
from backend.services.search import SearchService
from backend.services.settings import SettingsService

# ─── Settings & Infra Helpers ───


def get_torrserver_url() -> str:
    return load_settings()["torrserver_endpoint"]




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
) -> LibraryService:
    return LibraryService(
        library_repo=library_repo,
        torrserver_client=torrserver,
        settings_provider=get_torrserver_url,
        metadata_service=metadata_service,
    )


def get_collection_service(
    collection_repo: Annotated[CollectionRepository, Depends(get_collection_repo)],
) -> CollectionService:
    return CollectionService(collection_repo=collection_repo)


def get_history_service(
    history_repo: Annotated[HistoryRepository, Depends(get_history_repo)],
) -> HistoryService:
    return HistoryService(history_repo=history_repo)


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


@lru_cache
def get_playback_service() -> PlaybackService:
    """Application-scoped singleton provider for PlaybackService.

    Maintains active MPV player processes and IPC socket connections across HTTP requests.
    """
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
    )


def get_magnet_service(
    metadata_service: Annotated[MetadataService, Depends(get_metadata_service)],
    library_repo: Annotated[LibraryRepository, Depends(get_library_repo)],
) -> MagnetService:
    return MagnetService(
        torrserver_client=torrserver,
        settings_provider=get_torrserver_url,
        metadata_service=metadata_service,
        library_repo=library_repo,
    )


def get_search_service() -> SearchService:
    tz_cfg = get_torznab_config()
    rutor_provider = RuTorTorrServerProvider(
        torrserver_client=torrserver,
        base_url_provider=get_torrserver_url,
    )
    torznab_provider = TorznabProvider(config=tz_cfg)
    return SearchService(
        providers=[rutor_provider, torznab_provider],
        torrserver_client=torrserver,
        settings_provider=get_torrserver_url,
        torznab_config_provider=get_torznab_config,
    )


def get_settings_service() -> SettingsService:
    return SettingsService(
        torrserver_client=torrserver,
        settings_provider=get_torrserver_url,
    )
