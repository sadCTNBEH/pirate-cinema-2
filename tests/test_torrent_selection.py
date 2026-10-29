import asyncio
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from backend.infrastructure.torrserver import client as ts
from backend.models.playback import PlaybackState
from backend.repositories.db import Database
from backend.repositories.playback import PlaybackRepository
from backend.services.playback import PlaybackService
from backend.services.torrent_selection import (
    next_file,
    playable,
    select_files,
)


def video(name, id=7, size=500_000_000):
    return {'id': id, 'name': name.rsplit('/', 1)[-1], 'path': name, 'length': size}


@pytest.mark.parametrize('name', ['S01E03.mkv', 'S1E3.mp4', '1x03.avi',
    'Season 1 Episode 3.mkv', 'Season 1/Episode 03.mkv', 'S01/E03.mkv', 'Season 1/03.mkv'])
def test_number_formats(name):
    assert select_files([video(name)], season=1, episode=3)['file']['id'] == 7


def test_movie_and_samples():
    files = [video('sample.mp4', 0), video('Movie (2020).mkv', 13)]
    assert select_files(files)['file']['id'] == 13


def test_whole_season_and_multiple_seasons():
    files = [video(f'S{s:02}/Show.S{s:02}E{e:02}.mkv', s * 100 + e)
             for s in (1, 2) for e in range(1, 13)]
    assert select_files(files, season=2, episode=3)['file']['id'] == 203
    assert next_file(files, 103)['id'] == 104
    assert next_file(files, 112) is None  # no guess at a season boundary


def test_absolute_anime_requires_mapping():
    files = [video('[Group] Anime - 025 [1080p].mkv', 81)]
    assert select_files(files, season=2, episode=1)['file'] is None
    assert len(select_files(files, season=2, episode=1)['candidates']) == 1
    assert select_files(files, season=2, episode=1, absolute=25)['file']['id'] == 81
    assert select_files([video('Season 2/025.mkv')], season=2, episode=1, absolute=25)['file']
    assert select_files([video('03.mkv')], season=2, episode=3)['file'] is None


def test_release_season_supplies_context_but_collection_does_not():
    files = [video('03.mkv')]
    assert select_files(files, season=2, episode=3, release_title='Show S02')['file']
    assert select_files(files, season=2, episode=3, release_title='Show S01-S03')['file'] is None


@pytest.mark.parametrize('name', ['samples/Movie.mkv', 'trailer.mp4', 'preview.mkv',
    'extras/Movie.mkv', 'bonus.mkv', 'opening.mkv', 'ending.mp4', 'creditless OP.mkv',
    'NCOP.mkv', 'NCED.mkv', 'OP02.mkv', 'ED01.mkv', 'promo.mp4', 'captions.srt', 'poster.jpg'])
def test_extras_never_play(name):
    assert not playable(video(name))


def test_small_promo_and_real_title_boundaries():
    assert not playable(video('announcement.mp4', size=1_000_000))
    assert playable(video('The.Samples.of.Life.mkv')) is False
    assert playable(video('OpeningNight.mkv'))


def test_variants_need_choice_and_missing_episode_never_falls_back():
    files = [video('VoiceA/S01E03.mkv', 8), video('VoiceB/S01E03.mkv', 19)]
    result = select_files(files, season=1, episode=3)
    assert result['file'] is None and len(result['candidates']) == 2
    assert select_files(files, season=1, episode=4)['candidates'] == []
    assert next_file(files, 8) is None


@pytest.mark.parametrize('name', ['S01E03-E04.mkv', 'S01E03E04.mkv', 'S01E03-04.mkv'])
def test_multi_episode_files_are_not_exact(name):
    for ep in (3, 4):
        result = select_files([video(name)], season=1, episode=ep)
        assert result['file'] is None and result['candidates']


def test_specials_available_only_for_special_selection():
    files = [video('S00E01 OVA.mkv', 2), video('S01E01.mkv', 5)]
    assert select_files(files, season=1, episode=1)['file']['id'] == 5
    assert select_files(files, season=0, episode=1)['file']['id'] == 2
    assert not select_files([video('OVA 01.mkv')])['candidates']
    assert select_files([video('OVA.mkv')], release_title='Show OVA')['file']
    assert select_files([video('ONA S01E01.mkv')], season=1, episode=1)['file']


@pytest.mark.asyncio
async def test_confirmed_choice_persists_per_episode(tmp_path):
    repo = PlaybackRepository(Database(tmp_path / 'choices.sqlite'))
    server = MagicMock(torrent_video_files=AsyncMock(return_value=[
        video('A/S01E03.mkv', 11), video('B/S01E03.mkv', 22), video('S01E04.mkv', 31)]))
    service = PlaybackService(repo, MagicMock(), MagicMock(), MagicMock(), server, lambda: 'http://ts')
    assert (await service.select_torrent_file('hash', season=1, episode=3))['file'] is None
    assert (await service.select_torrent_file('hash', season=1, episode=3, file_id=22))['file']['id'] == 22
    recreated = PlaybackService(repo, MagicMock(), MagicMock(), MagicMock(), server, lambda: 'http://ts')
    assert (await recreated.select_torrent_file('hash', season=1, episode=3))['file']['id'] == 22
    assert repo.file_intent('hash', 22) == {'season': 1, 'episode': 3, 'absolute': None}
    assert (await recreated.select_torrent_file('hash', season=1, episode=4))['file']['id'] == 31
    assert repo.file_intent('hash', 31) == {'season': 1, 'episode': 4, 'absolute': None}
    server.torrent_video_files.return_value = [video('S01E03.mkv', 11)]
    assert (await recreated.select_torrent_file('hash', season=1, episode=3))['file']['id'] == 11


@pytest.mark.asyncio
@pytest.mark.parametrize('matrix', [False, True])
async def test_torrserver_paths_indices_cache_and_no_video_requests(monkeypatch, matrix):
    import json
    requests = []
    async def respond(request):
        requests.append(request)
        files = [{'id': 0, 'path': 'sample.mp4', 'length': 1000},
                 {'id': 17, 'path': 'Show/Season 1/03.mkv', 'length': 500_000_000}]
        data = {'data': json.dumps({'TorrServer': {'Files': files}})} if matrix else {'file_stats': files}
        return httpx.Response(200, json=data)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(ts, 'get_client', lambda: client)
        monkeypatch.setattr(ts, '_file_cache', {})
        files, _duplicate = await asyncio.gather(ts.torrent_video_files('http://ts', 'a' * 40),
                                               ts.torrent_video_files('http://ts', 'a' * 40))
        selected = select_files(files, season=1, episode=3)['file']
        assert selected['path'] == 'Show/Season 1/03.mkv'
        url = ts.stream_url('http://ts', 'a' * 40, selected['id'], selected['name'])
        assert parse_qs(urlsplit(url).query)['index'] == ['17']
        files[0]['name'] = 'mutated'
        cached = await ts.torrent_video_files('http://ts', 'a' * 40)
        assert cached[0]['name'] != 'mutated'
        assert len(requests) == 1 and requests[0].url.path == '/torrents'


@pytest.mark.asyncio
async def test_next_uses_episode_identity_not_adjacent_variant():
    files = [video('A/S01E03.mkv', 8), video('B/S01E03.mkv', 9),
             video('S01E04.mkv', 27), video('S02E01.mkv', 1)]
    server = MagicMock(torrent_video_files=AsyncMock(return_value=files))
    service = PlaybackService(MagicMock(), MagicMock(), MagicMock(), MagicMock(), server, lambda: 'http://ts')
    state = PlaybackState(hash='show', file_id=8, file_name='S01E03.mkv')
    service.active_states['show'] = state
    service.controllers['show'] = MagicMock()
    await service._refresh_next_available('show', files)
    assert service._next_candidates['show'][1]['file']['id'] == 27
    service.launch = AsyncMock(return_value='launched')
    assert await service.play_next_file('show', 8)
    assert service.launch.await_args.kwargs['command'].file_id == 27


@pytest.mark.asyncio
async def test_next_reuses_confirmed_variant(tmp_path):
    repo = PlaybackRepository(Database(tmp_path / 'choices.sqlite'))
    files = [video('S01E03.mkv', 8), video('A/S01E04.mkv', 15), video('B/S01E04.mkv', 27)]
    server = MagicMock(torrent_video_files=AsyncMock(return_value=files))
    service = PlaybackService(repo, MagicMock(), MagicMock(), MagicMock(), server, lambda: 'http://ts')
    await service.select_torrent_file('show', season=1, episode=4, file_id=27)
    assert (await service._next_torrent_file(files, 'show', 8))['id'] == 27


@pytest.mark.asyncio
async def test_selected_index_reaches_mpv_and_history_with_resume(monkeypatch, tmp_path):
    from backend.models.playback import PlayCommand
    from backend.repositories.history import HistoryRepository
    from backend.repositories.library import LibraryRepository
    from backend.repositories.metadata import MetadataRepository
    from backend.services import playback

    db = Database(tmp_path / 'history.sqlite')
    db.init_db()
    repo = PlaybackRepository(db)
    history = HistoryRepository(db)
    files = [video('sample.mp4', 0), video('Show/Season 1/03.mkv', 17), video('S01E04.mkv', 32)]
    server = MagicMock(torrent_video_files=AsyncMock(return_value=files),
                       save_torrent_to_db=AsyncMock(), stream_url=ts.stream_url)
    controller = MagicMock(is_running=False)
    monkeypatch.setattr(playback, 'load_settings', lambda: {'embedded_player': False})
    monkeypatch.setattr(playback, 'resolve_mpv_binary', lambda _: 'mpv')
    service = PlaybackService(repo, history, MetadataRepository(db), lambda: controller,
                              server, lambda: 'http://localhost:8090', library_repo=LibraryRepository(db))
    selected = (await service.select_torrent_file('a' * 40, season=1, episode=3))['file']
    command = PlayCommand(hash='a' * 40, file_id=selected['id'], file_name=selected['name'])
    assert await service.launch(command) == 'launched'
    assert parse_qs(urlsplit(controller.launch.call_args.kwargs['url']).query)['index'] == ['17']
    state = service.active_states['a' * 40]
    state.timecode, state.duration = 137, 1400
    repo.save_progress(state)
    assert await service.launch(command) == 'launched'
    assert controller.launch.call_args.kwargs['start_time'] == 137
    with db.get_connection() as conn:
        row = conn.execute('SELECT file_index,season,episode FROM media_file_history').fetchone()
        assert tuple(row) == (17, 1, 3)


def test_initial_null_time_position_does_not_expose_empty_native_panel():
    service = PlaybackService(MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), lambda: 'http://ts')
    state = PlaybackState(hash='show', file_id=3, file_name='S01E03.mkv')
    service.active_states['show'] = state
    service.controllers['show'] = MagicMock()
    service._handle_progress('show', 'time-pos', None)
    assert not state.is_ready
    service._handle_progress('show', 'time-pos', 0)
    assert state.is_ready
