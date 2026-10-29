import asyncio
from unittest.mock import MagicMock

import httpx
import pytest

from backend.services.introdb import IntroDB


def data(**updates):
    return dict(imdb_id='tt0903747', is_movie=False, season=1, episode=2,
                intro={'start_sec': 10, 'end_sec': 40, 'confidence': 0.95}, **updates)


def test_cache_identity_errors_and_rate_limit():
    async def run():
        repo = MagicMock()
        cache = {}
        repo.get_cached_metadata.side_effect = lambda key, ttl: cache.get(key)
        repo.save_cached_metadata.side_effect = lambda key, value, imdb: cache.update({key: value})
        requests = []
        def respond(request):
            requests.append(request)
            assert request.url.params['imdb_id'] == 'tt0903747'
            assert request.url.params['season'] == '1'
            return httpx.Response(200, json=data())
        client = IntroDB(repo, httpx.MockTransport(respond))
        assert await client.segments('12345', 1, 2) == []
        assert await client.segments('tt0903747', None, 2) == []
        assert len(await client.segments('tt0903747', 1, 2)) == 1
        assert len(await client.segments('tt0903747', 1, 2)) == 1
        assert len(requests) == 1
        assert await client.segments('tt0903747', 1, 3) == []  # wrong episode response
        assert len(requests) == 2
        repo.get_cached_metadata.side_effect = lambda *args: None
        for status in (404, 429, 503):
            client = IntroDB(repo, httpx.MockTransport(lambda request: httpx.Response(status)))
            assert await client.segments('tt0903747', 1, 2) == []
            if status != 404:
                assert client.retry_at > 0
        def offline(request):
            raise httpx.ConnectError('offline')
        assert await IntroDB(repo, httpx.MockTransport(offline)).segments('tt0903747', 1, 2) == []
        movie = IntroDB(repo, httpx.MockTransport(lambda request: httpx.Response(200, json={
            'imdb_id': 'tt0371746', 'is_movie': True, 'intro': {'start_sec': 1, 'end_sec': 20, 'confidence': 1}})))
        assert len(await movie.segments('tt0371746', movie=True)) == 1
    asyncio.run(run())


@pytest.mark.parametrize('start,end,confidence', [(10, 5, 1), (-1, 20, 1), (0, float('nan'), 1),
                                                    (0, 20, .5), (True, 20, 1), (0, 20, 2)])
def test_invalid_segments(start, end, confidence):
    assert IntroDB.validate({'intro': {'start_sec': start, 'end_sec': end, 'confidence': confidence}}) == []


def test_post_credit_scene_is_preserved_and_conflicts_rejected():
    result = IntroDB.validate({'outro': {'start_sec': 100, 'end_sec': 200, 'confidence': 1},
                               'post_credits': {'start_sec': 150, 'end_sec': 160}})
    assert result == [{'kind': 'outro', 'start': 100, 'end': 150, 'source': 'introdb'}]
    assert IntroDB.validate({'intro': {'start_sec': 0, 'end_sec': 20, 'confidence': 1},
                             'recap': {'start_sec': 10, 'end_sec': 30, 'confidence': 1}}) == []


def test_late_response_does_not_reach_next_episode():
    from backend.models.playback import PlaybackState
    from backend.services.playback import PlaybackService
    async def run():
        controller = MagicMock(is_running=True)
        repo = MagicMock()
        repo.get_imdb_id.return_value = 'tt0903747'
        service = PlaybackService(MagicMock(), MagicMock(), repo, lambda: controller, MagicMock(), lambda: '')
        service.controllers['hash'] = controller
        service.active_states['hash'] = PlaybackState(hash='hash', file_id=1)
        waiting, release = asyncio.Event(), asyncio.Event()
        async def response(*args, **kwargs):
            waiting.set()
            await release.wait()
            return [{'kind': 'intro', 'start': 10, 'end': 40, 'source': 'introdb'}]
        service._introdb.segments = response
        service._start_segments('hash', 1, 1)
        await waiting.wait()
        service.active_states['hash'] = PlaybackState(hash='hash', file_id=2)
        release.set()
        await asyncio.gather(*service._segment_tasks)
        controller.set_segments.assert_not_called()
    asyncio.run(run())
