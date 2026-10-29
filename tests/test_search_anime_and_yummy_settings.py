import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from backend.app import app
from backend.core.settings.user import DEFAULT_SETTINGS
from backend.infrastructure.catalog.yummyanime import YummyAnimeProvider
from backend.services.metadata import MetadataService
from backend.services.settings import SettingsService


def test_default_yummyanime_keys():
    assert DEFAULT_SETTINGS["yummyanime_public_key"] == "bz7uk_nr9bouyrn9"
    assert DEFAULT_SETTINGS["yummyanime_private_key"] == ""


def test_yummyanime_provider_default_credentials():
    provider = YummyAnimeProvider()
    token, priv = provider._get_credentials()
    assert token == "bz7uk_nr9bouyrn9"
    assert priv == ""
    assert provider.configured is True


def test_settings_service_yummyanime_keys():
    client_mock = MagicMock()
    service = SettingsService(torrserver_client=client_mock, settings_provider=lambda: "http://127.0.0.1:8090")
    
    settings = service.get_settings()
    assert "yummyanime_public_key" in settings
    assert "yummyanime_private_key" in settings

    service.update_settings({
        "yummyanime_public_key": "custom_key_123",
        "yummyanime_private_key": "secret_key_456"
    })
    
    updated = service.get_settings()
    assert updated["yummyanime_public_key"] == "custom_key_123"
    assert updated["yummyanime_private_key"] == "secret_key_456"

    # Restore default for other tests
    service.update_settings({
        "yummyanime_public_key": "bz7uk_nr9bouyrn9",
        "yummyanime_private_key": ""
    })


def test_unified_catalog_include_anime_flag():
    service = object.__new__(MetadataService)
    service.search_catalog = AsyncMock(return_value=[{"id": "tt1", "title": "Movie"}])
    service.anime_catalog = AsyncMock(return_value=[{"id": "shikimori:1", "title": "Anime"}])

    # With anime
    results_with = asyncio.run(service.unified_catalog("Naruto", include_anime=True))
    assert any(item["id"] == "shikimori:1" for item in results_with)
    assert service.anime_catalog.await_count == 1

    service.anime_catalog.reset_mock()

    # Without anime
    results_without = asyncio.run(service.unified_catalog("Naruto", include_anime=False))
    assert not any(item["id"] == "shikimori:1" for item in results_without)
    assert service.anime_catalog.await_count == 0


def test_meta_anime_endpoint():
    client = TestClient(app)
    with patch("backend.services.metadata.MetadataService.anime_catalog", new_callable=AsyncMock) as mock_anime:
        mock_anime.return_value = [{"id": "shikimori:20", "title": "Naruto"}]
        response = client.get("/api/library/meta/anime?q=Naruto")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "shikimori:20"
