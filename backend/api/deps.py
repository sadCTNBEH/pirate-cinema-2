import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends

from backend.core.settings import get_data_dir, get_torznab_config, load_settings
from backend.infrastructure.catalog import cinemeta
from backend.infrastructure.mpv.controller import MPVController
from backend.infrastructure.search import RuTorTorrServerProvider, TorznabProvider
from backend.infrastructure.torrserver import client as torrserver
from backend.repositories.audio import AudioRepository
from backend.repositories.db import Database
from backend.repositories.history import HistoryRepository
from backend.repositories.library import LibraryRepository
from backend.repositories.metadata import MetadataRepository
from backend.repositories.playback import PlaybackRepository
from backend.services.library import LibraryService
from backend.services.magnet import MagnetService
from backend.services.metadata import MetadataService
from backend.services.playback import PlaybackService
from backend.services.search import SearchService
from backend.services.settings import SettingsService

# ─── Settings & Infra Helpers ───


def get_torrserver_url() -> str:
    return load_settings()["torrserver_endpoint"]


def resolve_mpv_binary(prefs: dict) -> Path:
    if prefs.get("player_path"):
        custom_path = Path(prefs["player_path"])
        if custom_path.is_file():
            return custom_path

    if sys.platform == "win32":
        mpv_bin = get_data_dir() / "vendor" / "mpv" / "mpv.exe"
        if not mpv_bin.is_file():
            prog_files = (
                Path(os.environ.get("ProgramFiles", "C:/Program Files"))
                / "MPV Player"
                / "mpv.exe"
            )
            if prog_files.is_file():
                mpv_bin = prog_files
    else:
        mpv_bin = get_data_dir() / "vendor" / "mpv" / "mpv"

    if not mpv_bin.is_file():
        which_mpv = shutil.which("mpv")
        mpv_bin = Path(which_mpv) if which_mpv else Path("mpv")

    return mpv_bin


# ─── Repositories Providers ───


@lru_cache
def get_database() -> Database:
    return Database()


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


@lru_cache
def get_playback_service() -> PlaybackService:
    """Application-scoped singleton provider for PlaybackService.

    Maintains active MPV player processes and IPC socket connections across HTTP requests.
    """
    db = get_database()
    return PlaybackService(
        playback_repo=PlaybackRepository(db=db),
        history_repo=HistoryRepository(db=db),
        metadata_repo=MetadataRepository(db=db),
        mpv_controller_factory=MPVController,
        torrserver_client=torrserver,
        settings_provider=get_torrserver_url,
    )


def get_magnet_service(
    metadata_service: Annotated[MetadataService, Depends(get_metadata_service)],
) -> MagnetService:
    return MagnetService(
        torrserver_client=torrserver,
        settings_provider=get_torrserver_url,
        metadata_service=metadata_service,
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
