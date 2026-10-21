"""Online history service."""

import logging

from backend.api.schemas.online import OnlineHistoryItem
from backend.exceptions import NotFoundError
from backend.repositories.online import OnlineRepository

logger = logging.getLogger(__name__)


class OnlineHistoryService:
    def __init__(self, repo: OnlineRepository):
        self._repo = repo

    def list_history(self, limit: int = 100) -> list[OnlineHistoryItem]:
        rows = self._repo.list_history(limit=limit)
        items: list[OnlineHistoryItem] = []
        for r in rows:
            items.append(
                OnlineHistoryItem(
                    item_id=r["item_id"],
                    provider=r["provider"],
                    title=r["title"],
                    thumbnail=r.get("thumbnail"),
                    duration=r.get("duration"),
                    playback_timecode=r.get("playback_timecode") or 0,
                    playback_duration=r.get("playback_duration") or 0,
                    is_watched=bool(r.get("is_watched")),
                    last_played_at=r["last_played_at"],
                    launch_count=r.get("launch_count") or 1,
                )
            )
        return items

    def mark_played(
        self,
        provider: str,
        item_id: str,
        title: str,
        thumbnail: str | None = None,
        duration: int | None = None,
    ) -> None:
        self._repo.mark_played(
            provider=provider,
            item_id=item_id,
            title=title,
            thumbnail=thumbnail,
            duration=duration,
        )

    def update_progress(
        self,
        provider: str,
        item_id: str,
        timecode: int,
        duration: int,
    ) -> None:
        self._repo.update_progress(
            provider=provider,
            item_id=item_id,
            timecode=timecode,
            duration=duration,
        )

    def delete_history_item(self, provider: str, item_id: str) -> None:
        deleted = self._repo.delete_history_item(provider, item_id)
        if not deleted:
            raise NotFoundError(f"Запись истории '{provider}:{item_id}' не найдена")

    def clear_history(self) -> None:
        self._repo.clear_history()
