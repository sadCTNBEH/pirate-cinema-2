import asyncio

import httpx
import pytest

from backend.exceptions import ExternalServiceError
from backend.infrastructure.catalog.yummyanime import YummyAnimeProvider


def test_normalize_yummy_titles_and_episodes():
    result = YummyAnimeProvider.normalize({'anime_id': 111, 'title': 'Наруто',
        'other_titles': ['Naruto', 'ナルト'], 'episodes': {'aired': 220, 'count': 220},
        'poster': {'big': '//imgproxy.yani.tv/poster.webp'}, 'remote_ids': {'shikimori_id': 20}})
    assert result['id'] == 'yummy:111'
    assert result['original_title'] == 'Naruto'
    assert result['shikimori_id'] == 20
    assert result['episodes'] == len(result['videos']) == 220
    assert result['poster_url'].startswith('https://')
    assert 'stream_url' not in result


def test_public_token_header_and_safe_metadata():
    def handler(request):
        assert request.headers['X-Application'] == 'test-public-token'
        assert 'Authorization' not in request.headers
        assert request.url.path == '/anime/111'
        return httpx.Response(200, json={'response': {'anime_id': 111, 'title': 'Наруто',
            'blocked': {'blocked': False}, 'episodes': {'count': 2},
            'videos': [{'iframe_url': '//example.org/player'}]}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await YummyAnimeProvider('test-public-token', client).detail('111')
            assert result['blocked'] is False
            assert len(result['videos']) == 2
            assert 'iframe_url' not in str(result)
            assert 'test-public-token' not in str(result)
    asyncio.run(run())


def test_upstream_error_does_not_expose_response_or_token():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(403, text='test-public-token'))) as client:
            with pytest.raises(ExternalServiceError) as error:
                await YummyAnimeProvider('test-public-token', client).fetch(search='Naruto')
            assert 'test-public-token' not in str(error.value)
    asyncio.run(run())


def test_current_season_uses_official_catalog_filters():
    def handler(request):
        assert request.url.path == '/anime'
        assert request.url.params['sort'] == 'views'
        assert request.url.params['sort_forward'] == 'false'
        assert request.url.params['season'] in ('1', '2', '3', '4')
        assert request.url.params['from_year'] == request.url.params['to_year']
        return httpx.Response(200, json={'response': []})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await YummyAnimeProvider('test-public-token', client).fetch('season') == []
    asyncio.run(run())

def test_player_options_include_cvh_and_filter_unsafe_urls():
    items = YummyAnimeProvider.normalize_players([
        {'video_id': 1, 'number': '2', 'iframe_url': '//cvh.yani.tv/player?id=1',
         'data': {'player': 'Плеер CVH', 'dubbing': 'Субтитры'}},
        {'video_id': 2, 'iframe_url': 'javascript:alert(1)'},
        {'video_id': 3, 'iframe_url': 'https://user:password@example.org/player'},
        {'video_id': 4, 'iframe_url': 'http://example.org/player'},
        {'video_id': 5, 'iframe_url': 'https://player.aksor.tv/video/1', 'data': {'player':'Плеер Aksor'}},
        {'video_id': 6, 'iframe_url': 'https://other.example/player', 'data': {'player':'Aksor'}},
        {'video_id': 7, 'iframe_url': 'https://player.aksor.tv/video/2', 'data': {'player':'Другой'}},
        {'video_id': 1, 'iframe_url': 'https://cvh.yani.tv/player?id=1'},
    ])
    assert len(items) == 1
    assert items[0]['player'] == 'Плеер CVH'
    assert items[0]['episode'] == '2'
    assert items[0]['url'].startswith('https://')
    assert items[0]['dubbing'] == 'Субтитры'


def test_players_endpoint_uses_documented_video_route():
    def handler(request):
        assert request.url.path == '/anime/111/videos'
        assert request.headers['X-Application'] == 'test-public-token'
        return httpx.Response(200, json={'response': [{'video_id': 10, 'number': '1',
            'iframe_url': '//kodik.yani.tv/player', 'data': {'player': 'Kodik'}}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            items = await YummyAnimeProvider('test-public-token', client).players('111')
            assert items[0]['id'] == '10'
            assert 'test-public-token' not in str(items)
    asyncio.run(run())


def test_parts_use_official_viewing_order_and_keep_movies():
    def handler(request):
        assert request.url.path == '/anime/947'
        return httpx.Response(200, json={'response': {'anime_id':947, 'title':'Nagatoro',
            'viewing_order':[{'anime_id':947,'title':'Nagatoro'},
                {'anime_id':4616,'title':'Nagatoro 2','year':2023,'type':{'name':'Сериал'}},
                {'anime_id':99,'title':'Movie','type':{'name':'Фильм'}}, {'title':'Missing ID'}]}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            parts = await YummyAnimeProvider('test-public-token',client).parts('947')
            assert [part['id'] for part in parts] == ['947','4616','99']
            assert parts[-1]['type'] == 'Фильм'
    asyncio.run(run())


def test_parts_route_uses_object_cache_envelope():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from backend.api.routers.library import yummy_parts
    parts = [{'id':'947','title':'Nagatoro'}]
    async def cache(key, fetch):
        data = await fetch()
        assert isinstance(data, dict)  # MetadataCache requires a JSON object.
        return data
    service = SimpleNamespace(_swr=cache, _yummy=SimpleNamespace(parts=AsyncMock(return_value=parts)))
    assert asyncio.run(yummy_parts(947, service)) == parts
