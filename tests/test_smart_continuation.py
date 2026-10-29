import asyncio
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.infrastructure.mpv.controller import MPVController
from backend.models.playback import PlaybackState, PlayCommand
from backend.models.search import SearchResult
from backend.repositories.db import Database
from backend.repositories.history import HistoryRepository
from backend.repositories.metadata import MetadataRepository
from backend.repositories.playback import PlaybackRepository
from backend.services.continuation import catalog_next, release_matches
from backend.services.playback import PlaybackService


def catalog(*episodes):
    return {'title': 'Example', 'year': 2020, 'videos': [
        {'season': s, 'episode': e, 'released': date} for s, e, date in episodes]}


def player(tmp_path=None):
    if tmp_path:
        db = Database(tmp_path / 'history.sqlite')
        db.init_db()
        repo, history, metadata = PlaybackRepository(db), HistoryRepository(db), MetadataRepository(db)
    else:
        repo, history, metadata = MagicMock(), MagicMock(), MagicMock()
    controller = MagicMock(is_running=True)
    server = MagicMock(torrent_video_files=AsyncMock(return_value=[
        {'id': 3, 'name': 'Example.S01E03.mkv'}, {'id': 4, 'name': 'Example.S01E04.mkv'}]),
        save_torrent_to_db=AsyncMock(), stream_url=MagicMock(return_value='http://localhost/stream'))
    service = PlaybackService(repo, history, metadata, lambda: controller, server, lambda: 'http://ts')
    state = PlaybackState('old', 3, file_name='Example.S01E03.mkv', timecode=500, duration=600, is_ready=True)
    service.controllers['old'] = controller
    service.active_states['old'] = state
    service.loop = asyncio.get_running_loop()
    service._schedule_save = MagicMock()
    return service, state, controller


@pytest.mark.asyncio
async def test_countdown_cancel_only_current_transition_and_duplicate_eof():
    service, state, controller = player()
    await service._refresh_next_available('old')
    service.play_next_file = AsyncMock(return_value=True)
    service._file_intents[('old', 3)] = {'season': None, 'episode': None, 'absolute': None}
    service._handle_progress('old', 'time-pos', 595)
    assert service.continuation.offer['label'] == 'Следующая серия: S01E04'
    assert service.continuation.offer['remaining'] is None
    await service.continuation.eof(state)
    await asyncio.sleep(0)
    assert service.continuation.offer['remaining'] == 10
    await service.continuation.act('cancel', service.continuation.serial)
    service._handle_end('old', 'eof')
    await asyncio.sleep(.01)
    assert service._auto_next_enabled
    assert service.continuation.offer is None
    service.play_next_file.assert_not_awaited()
    assert any(c.args[0][1] == 'cinema-continuation' for c in controller.send_command.call_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['stop', 'launch', 'manual'])
async def test_old_offer_and_commands_expire(change):
    service, state, _ = player()
    await service._refresh_next_available('old')
    await service.continuation.eof(state)
    token = service.continuation.serial
    if change == 'stop':
        service.stop()
    else:
        service._begin_launch()
    assert service.continuation.offer is None
    assert not await service.continuation.act('watch', token)
    await service.continuation.eof(state if change == 'stop' else PlaybackState('old', 3))
    assert service.continuation.offer is None
    await asyncio.sleep(0)


@pytest.mark.parametrize('episodes,expected,message', [
    ([(1, 5, '2020-01-01'), (1, 6, '2020-01-02')], (1, 6), ''),
    ([(1, 12, '2020-01-01'), (2, 1, '2021-01-02')], (2, 1), ''),
    ([(1, 5, '2020-01-01'), (1, 6, '2999-01-01')], None, 'ещё не вышла'),
    ([(1, 5, '2020-01-01'), (1, 6, '')], None, 'не подтверждена'),
    ([(1, 5, '2020-01-01'), (1, 7, '2020-01-02')], None, 'метаданных'),
])
def test_catalog_no_guessing(episodes, expected, message):
    target, reason = catalog_next(catalog(*episodes), episodes[0][:2])
    assert (target['season'], target['episode']) == expected if target else expected is None
    assert message in reason


@pytest.mark.parametrize('title,accepted', [
    ('Example (2020) S01E06 1080p', True),
    ('Example (2020) S01 720p', True),
    ('Example (2024) S01E06', False),
    ('Example (2020) S02E06', False),
    ('Example (2020) S01E06 sample', False),
    ('Example Remake (2024) S01E06', False),
    ('Examples (2020) S01E06', False),
])
def test_release_identity_and_samples(title, accepted):
    assert release_matches(SearchResult(title=title, infohash='abc'), catalog(),
                           {'season': 1, 'episode': 6, 'absolute': None}) is accepted


@pytest.mark.asyncio
@pytest.mark.parametrize('count', [0, 1, 3])
async def test_external_search_requires_confirmation_then_exact_file(count):
    service, state, _ = player()
    state.file_name = 'Example.S01E05.mkv'
    service._metadata.get_imdb_id.return_value = 'tt123'
    service._metadata_service = SimpleNamespace(movie_meta=AsyncMock(return_value=catalog(
        (1, 5, '2020-01-01'), (1, 6, '2020-01-02'))))
    flow = service.continuation
    flow.search = SimpleNamespace(search_torrents=AsyncMock(return_value=[SearchResult(
        title='Example (2020) S01E06 1080p', infohash=str(i), magnet='magnet:' + str(i),
        quality='1080p', size=1234567890, seeders=10) for i in range(count)]))
    flow.magnet = SimpleNamespace(add_magnet=AsyncMock(return_value={'hash': 'new'}))
    flow.attach(state)
    await flow.find()
    assert flow.offer['status'] == ('results' if count else 'empty')
    flow.magnet.add_magnet.assert_not_awaited()
    if count:
        service.select_torrent_file = AsyncMock(return_value={
            'file': {'id': 17, 'name': 'S01E06.mkv'}, 'metadata_ready': True})
        service.launch = AsyncMock(return_value='launched')
        assert await flow.act('choose', flow.serial, count-1)
        assert flow.magnet.add_magnet.await_args.args[0] == 'magnet:' + str(count-1)
        assert service.select_torrent_file.await_args.kwargs['episode'] == 6
        assert service.launch.await_args.args[0].file_id == 17


@pytest.mark.asyncio
async def test_future_episode_does_not_search_and_season_boundary_in_current_torrent():
    service, state, _ = player()
    state.file_name = 'S01E12.mkv'
    service._metadata.get_imdb_id.return_value = 'tt123'
    service._metadata_service = SimpleNamespace(movie_meta=AsyncMock(return_value=catalog(
        (1, 12, '2020-01-01'), (2, 1, '2999-01-01'))))
    flow = service.continuation
    flow.search = SimpleNamespace(search_torrents=AsyncMock())
    flow.attach(state)
    await flow.find()
    flow.search.search_torrents.assert_not_awaited()
    assert 'ещё не вышла' in flow.offer['label']
    service._metadata_service.movie_meta.return_value = catalog((1, 12, '2020-01-01'), (2, 1, '2021-01-01'))
    files = [{'id': 3, 'name': 'S01E12.mkv'}, {'id': 99, 'name': 'S02E01.mkv'}]
    assert (await service._next_torrent_file(files, 'old', 3))['id'] == 99
    assert service._file_intents[('old', 99)]['season'] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('duration,seek', [(1810, True), (2200, False), (0, False)])
async def test_transfer_waits_for_compatible_duration(duration, seek):
    service, state, controller = player()
    state.resume_candidate = {'playback_timecode': 900, 'playback_duration': 1800, 'is_watched': 0}
    service._handle_progress('old', 'duration', duration)
    seeks = [c.args[0] for c in controller.send_command.call_args_list if c.args[0][0] == 'seek']
    assert bool(seeks) is seek
    if seek:
        assert seeks == [['seek', 900, 'absolute+exact']]
    if duration == 0:
        assert state.resume_candidate is not None


@pytest.mark.asyncio
async def test_sqlite_cross_release_episode_survives_restart_without_merging_titles(tmp_path):
    service, state, _ = player(tmp_path)
    for hash_, identity in [('old', 'tt123'), ('new', 'tt123'), ('remake', 'tt456')]:
        service._metadata.save_full_metadata(hash_, 'Example', '', 2020, None, '', '[]', None, identity)
    service._history.mark_played('old', 3, 'S01E03.mkv', None, 1, 3)
    state.timecode, state.duration = 900, 1800
    service._repo.save_progress(state)
    restarted = PlaybackRepository(Database(tmp_path / 'history.sqlite'))
    assert restarted.logical_progress('new', 1, 3)['playback_timecode'] == 900
    assert restarted.logical_progress('new', 2, 3) is None
    assert restarted.logical_progress('remake', 1, 3) is None
    assert restarted.logical_progress('new', latest=True)['episode'] == 3
    service._torrserver.torrent_video_files.return_value = [{'id': 33, 'name': 'S01E03.mkv'}, {'id': 34, 'name': 'S01E04.mkv'}]
    assert (await service.select_torrent_file('new'))['file']['id'] == 33
    assert (await service.select_torrent_file('new', season=1))['file']['id'] == 33
    assert len(service._history.list_history()) == 1


def test_mpv_queued_old_observations_are_ignored_until_path_probe():
    controller = MPVController()
    controller.is_running = True
    controller._awaiting_media = True
    controller._media_probe = 100010
    controller.media_url = 'http://new'
    events = [
        {'event': 'property-change', 'name': 'time-pos', 'data': 999},
        {'event': 'end-file', 'reason': 'eof'},
        {'event': 'file-loaded'},
        {'request_id': 100010, 'error': 'success', 'data': 'http://new'},
        {'request_id': 100011, 'error': 'success', 'data': 1800},
        {'event': 'property-change', 'name': 'time-pos', 'data': 2},
    ]
    controller.pipe = io.BytesIO(('\n'.join(json.dumps(e) for e in events)+'\n').encode())
    controller.send_command = MagicMock()
    progress, ends = [], []
    controller.on_progress = lambda n, v: progress.append((n, v))
    controller.on_end = ends.append
    controller._reader_loop()
    assert ('time-pos', 999) not in progress
    assert ('duration', 1800) in progress and ('time-pos', 2) in progress
    assert 'eof' not in ends

@pytest.mark.asyncio
async def test_real_sqlite_launch_transfer_and_catalog_binding(tmp_path, monkeypatch):
    from backend.services import playback
    service, state, controller = player(tmp_path)
    monkeypatch.setattr(playback, 'load_settings', lambda: {'embedded_player': False})
    monkeypatch.setattr(playback, 'resolve_mpv_binary', lambda _: 'mpv')
    service._metadata.bind_catalog_identity('old', 'tt123')
    service._history.mark_played('old', 3, 'S01E03.mkv', None, 1, 3)
    state.timecode, state.duration = 900, 1800
    service._repo.save_progress(state)
    service._torrserver.torrent_video_files.return_value = [{'id': 33, 'name': 'S01E03.mkv'}]
    selected = await service.select_torrent_file('new', media_id='tt123')
    assert selected['file']['id'] == 33  # restores the last logical episode
    assert await service.launch(PlayCommand('new', 33, 'S01E03.mkv')) == 'launched'
    new_state = service.active_states['new']
    assert new_state.timecode == 0 and new_state.resume_candidate['playback_timecode'] == 900
    service._handle_progress('new', 'duration', 1810)
    assert new_state.timecode == 900
    service._repo.save_progress(new_state)
    assert service._repo.get_previous_progress('new',33)['playback_timecode'] == 900
    assert service._repo.get_previous_progress('old',3)['playback_timecode'] == 900
    with pytest.raises(ValueError):
        service._metadata.bind_catalog_identity('new', 'tt456')


@pytest.mark.asyncio
async def test_seek_after_eof_cancels_countdown_and_duplicate_open_preserves_offer():
    service, state, _ = player()
    await service._refresh_next_available('old')
    await service.continuation.eof(state)
    await asyncio.sleep(0)
    offer = service.continuation.offer
    await service.launch(PlayCommand('old', 3, state.file_name))
    assert service.continuation.offer is offer
    service.play_next_file = AsyncMock()
    service.send_command(['seek', -10, 'relative'])
    await service.continuation.eof(state)
    await asyncio.sleep(0)
    assert service.continuation.offer is None
    service.play_next_file.assert_not_awaited()


def test_absolute_number_only_from_explicit_catalog_mapping():
    meta = catalog((1, 24, '2020-01-01'), (2, 1, '2021-01-01'))
    meta['videos'][1]['absolute_episode'] = 25
    target, _ = catalog_next(meta, (1,24))
    assert target['absolute'] == 25
    assert release_matches(SearchResult(title='Example (2020) - 025 1080p', infohash='abc'),meta,target)


@pytest.mark.asyncio
async def test_late_search_cannot_reopen_cancelled_offer():
    service, state, _ = player()
    service._metadata.get_imdb_id.return_value='tt123'
    service._metadata_service=SimpleNamespace(movie_meta=AsyncMock(return_value=catalog(
        (1,3,'2020-01-01'),(1,4,'2020-01-02'))))
    entered, release = asyncio.Event(), asyncio.Event()
    async def search(*args,**kwargs):
        entered.set(); await release.wait(); return []
    flow=service.continuation
    flow.search=SimpleNamespace(search_torrents=search)
    flow.attach(state)
    pending=asyncio.create_task(flow.find())
    await entered.wait()
    await flow.act('cancel',flow.serial)
    release.set(); await pending
    assert flow.offer is None

@pytest.mark.asyncio
async def test_ambiguous_external_video_requires_separate_file_confirmation():
    service, state, _ = player()
    flow=service.continuation
    flow.attach(state)
    flow.magnet=SimpleNamespace(add_magnet=AsyncMock(return_value={'hash':'new'}))
    flow.offer={'status':'results','label':'Next','target':{'season':1,'episode':4,'absolute':None},
                'media_id':'tt123','meta_title':'Example','year':2020,
                'results':[{'title':'Example (2020) S01E04','magnet':'magnet:test'}]}
    service.select_torrent_file=AsyncMock(side_effect=[
        {'file':None,'metadata_ready':True,'candidates':[{'id':18,'name':'video.mkv'}]},
        {'file':{'id':18,'name':'video.mkv'}}])
    service.launch=AsyncMock()
    assert await flow.act('choose',flow.serial,0)
    assert flow.offer['status']=='files'
    service.launch.assert_not_awaited()
    assert await flow.act('file',flow.serial,0)
    assert service.select_torrent_file.await_args.kwargs['file_id']==18
    assert service.launch.await_args.args[0].file_id==18
