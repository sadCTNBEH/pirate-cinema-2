import tempfile
from pathlib import Path

import pytest

from backend.repositories.collections import CollectionRepository
from backend.repositories.db import Database
from backend.services.collections import CollectionService


@pytest.mark.anyio
async def test_collections_are_independent_and_keep_latest_metadata():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()
        service = CollectionService(CollectionRepository(db))

        item = {
            "media_id": "tt0133093",
            "title": "The Matrix",
            "title_ru": "The Matrix",
            "poster_url": "https://example.test/matrix.jpg",
            "year": 1999,
            "rating": 8.7,
            "overview": "A hacker learns the truth.",
            "overview_ru": None,
            "genres": ["Action", "Science Fiction"],
            "media_type": "movie",
        }

        await service.add_item("favorites", item)
        await service.add_item("watch_later", item)

        item["title_ru"] = "Matrix"
        await service.add_item("favorites", item)

        favorites = await service.get_items("favorites")
        assert len(favorites) == 1
        assert favorites[0]["title_ru"] == "Matrix"
        assert favorites[0]["genres"] == ["Action", "Science Fiction"]

        memberships = await service.get_memberships("tt0133093")
        assert memberships == {"favorites", "watch_later"}

        assert await service.remove_item("favorites", "tt0133093") is True
        assert await service.get_memberships("tt0133093") == {"watch_later"}
