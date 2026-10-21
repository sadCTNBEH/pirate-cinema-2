"""Playlist management service."""

import logging

from backend.api.schemas.online import OnlineSearchResult, Playlist
from backend.exceptions import NotFoundError
from backend.repositories.online import OnlineRepository

logger = logging.getLogger(__name__)


class PlaylistService:
    def __init__(self, repo: OnlineRepository):
        self._repo = repo

    def create_playlist(self, title: str) -> Playlist:
        cleaned = title.strip()
        if not cleaned:
            raise ValueError("Название плейлиста не может быть пустым")
        return self._repo.create_playlist(cleaned)

    def list_playlists(self) -> list[Playlist]:
        return self._repo.list_playlists()

    def get_playlist(self, playlist_id: str) -> Playlist:
        pl = self._repo.get_playlist(playlist_id)
        if not pl:
            raise NotFoundError(f"Плейлист '{playlist_id}' не найден")
        return pl

    def update_playlist(self, playlist_id: str, title: str) -> Playlist:
        cleaned = title.strip()
        if not cleaned:
            raise ValueError("Название плейлиста не может быть пустым")
        updated = self._repo.update_playlist(playlist_id, cleaned)
        if not updated:
            raise NotFoundError(f"Плейлист '{playlist_id}' не найден")
        return self.get_playlist(playlist_id)

    def delete_playlist(self, playlist_id: str) -> None:
        deleted = self._repo.delete_playlist(playlist_id)
        if not deleted:
            raise NotFoundError(f"Плейлист '{playlist_id}' не найден")

    def add_item(self, playlist_id: str, item: OnlineSearchResult) -> Playlist:
        # Verify playlist exists
        self.get_playlist(playlist_id)
        added = self._repo.add_item_to_playlist(playlist_id, item)
        if not added:
            raise NotFoundError(f"Не удалось добавить видео в плейлист '{playlist_id}'")
        return self.get_playlist(playlist_id)

    def remove_item(self, playlist_id: str, item_id: str) -> Playlist:
        # Verify playlist exists
        self.get_playlist(playlist_id)
        removed = self._repo.remove_item_from_playlist(playlist_id, item_id)
        if not removed:
            raise NotFoundError(f"Элемент '{item_id}' не найден в плейлисте '{playlist_id}'")
        return self.get_playlist(playlist_id)
