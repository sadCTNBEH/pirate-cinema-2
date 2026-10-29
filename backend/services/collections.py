import json
import sqlite3
from typing import Any

import anyio

from backend.exceptions import DatabaseError
from backend.repositories.collections import CollectionRepository

COLLECTION_NAMES = {"favorites", "watch_later"}


class CollectionService:
    def __init__(self, collection_repo: CollectionRepository):
        self._collection_repo = collection_repo

    async def canonicalize_alias(self, alias, canonical):
        await anyio.to_thread.run_sync(self._collection_repo.canonicalize_alias, alias, canonical)

    async def get_items(self, list_name: str) -> list[dict[str, Any]]:
        self._validate_list_name(list_name)
        try:
            items = await anyio.to_thread.run_sync(
                self._collection_repo.list_items, list_name
            )
        except sqlite3.Error as e:
            raise DatabaseError("Database error while loading collection") from e

        for item in items:
            try:
                genres = json.loads(item.pop("genres_json", "[]"))
                item["genres"] = genres if isinstance(genres, list) else []
            except (json.JSONDecodeError, TypeError):
                item["genres"] = []
        return items

    async def get_memberships(self, media_id: str) -> set[str]:
        try:
            return await anyio.to_thread.run_sync(
                self._collection_repo.list_memberships, media_id
            )
        except sqlite3.Error as e:
            raise DatabaseError(
                "Database error while loading collection membership"
            ) from e

    async def add_item(self, list_name: str, item: dict[str, Any]) -> None:
        self._validate_list_name(list_name)
        try:
            await anyio.to_thread.run_sync(
                self._collection_repo.save_item, list_name, item
            )
        except sqlite3.Error as e:
            raise DatabaseError("Database error while saving collection item") from e

    async def remove_item(self, list_name: str, media_id: str) -> bool:
        self._validate_list_name(list_name)
        try:
            return await anyio.to_thread.run_sync(
                self._collection_repo.remove_item, list_name, media_id
            )
        except sqlite3.Error as e:
            raise DatabaseError("Database error while removing collection item") from e

    @staticmethod
    def _validate_list_name(list_name: str) -> None:
        if list_name not in COLLECTION_NAMES:
            raise ValueError(f"Unsupported collection: {list_name}")
