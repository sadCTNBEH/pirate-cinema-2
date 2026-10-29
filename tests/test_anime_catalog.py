import asyncio
from unittest.mock import AsyncMock

from backend.infrastructure.catalog.anime import AnimeProvider
from backend.services.metadata import MetadataService


def test_anime_metadata_and_episodes():
    item = AnimeProvider.normalize({'id': 20, 'name': 'Naruto', 'russian': 'Наруто',
        'japanese': 'ナルト', 'kind': 'tv', 'episodes': 220, 'episodesAired': 0,
        'genres': [{'name': 'Action', 'russian': 'Экшен'}], 'score': '8.0'})
    assert item['id'] == 'shikimori:20'
    assert set(['Naruto', 'Наруто', 'ナルト']) <= set(item['aliases'])
    assert len(item['videos']) == 220
    assert item['genres'] == ['Экшен']
    assert 'stream_url' not in item


def test_unified_search_deduplicates_aliases():
    service = object.__new__(MetadataService)
    service.search_catalog = AsyncMock(return_value=[{'id': 'tt1', 'title': 'Naruto'}])
    service.anime_catalog = AsyncMock(return_value=[{'id': 'shikimori:20', 'title': 'Наруто', 'aliases': ['Naruto']}])
    items = asyncio.run(service.unified_catalog('Наруто'))
    assert [item['id'] for item in items] == ['shikimori:20']
    assert service.search_catalog.await_count == 2


def test_unified_search_survives_anime_outage():
    service = object.__new__(MetadataService)
    service.search_catalog = AsyncMock(return_value=[{'id': 'tt1', 'title': 'Movie'}])
    service.anime_catalog = AsyncMock(side_effect=TimeoutError)
    assert len(asyncio.run(service.unified_catalog('Movie'))) == 1


def test_unified_search_survives_movie_outage():
    service = object.__new__(MetadataService)
    service.search_catalog = AsyncMock(side_effect=TimeoutError)
    service.anime_catalog = AsyncMock(return_value=[{'id': 'shikimori:20', 'title': 'Наруто'}])
    assert asyncio.run(service.unified_catalog('Naruto'))[0]['id'] == 'shikimori:20'
