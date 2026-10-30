import io
import logging
import zipfile
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from backend.infrastructure.mpv.controller import MPVController
from backend.models.playback import PlaybackState
from backend.repositories.db import Database
from backend.repositories.playback import PlaybackRepository
from backend.services.subtitles import SubtitleService, _RedactKey

SRT = b'1\n00:00:01,000 --> 00:00:02,000\nHello\n'


def test_provider_key_is_redacted_in_http_logs():
    record = logging.LogRecord('httpx', logging.INFO, '', 1, 'HTTP Request: %s',
                               ('https://api.subdl.com/api/v1/subtitles?api_key=private-key&film_name=Film',), None)
    _RedactKey().filter(record)
    assert 'private-key' not in record.getMessage()
    assert 'film_name=Film' in record.getMessage()


def test_sync_survives_restart_and_is_scoped_to_file(tmp_path):
    path = tmp_path / 'history.db'
    db = Database(path)
    db.init_db()
    repo = PlaybackRepository(db)
    repo.save_sync('film', 1, 'sub-delay', -1.5)
    repo.save_sync('film', 1, 'audio-delay', .5)
    repo = PlaybackRepository(Database(path))
    assert repo.get_sync('film', 1) == (-1.5, .5)
    assert repo.get_sync('film', 2) == (0, 0)
    assert repo.get_sync('other', 1) == (0, 0)
    repo.save_sync('film', 1, 'sub-delay', 0)
    assert repo.get_sync('film', 1) == (0, .5)
    repo.save_sync('film', 1, 'audio-delay', float('nan'))
    assert repo.get_sync('film', 1) == (0, .5)
    controller = MPVController()
    controller.send_command = Mock()
    controller.configure_sync(-1.5, .5)
    controller.load_file('one.mkv', 'One')
    assert any('sub-delay=-1.5,audio-delay=0.5' in str(call) for call in controller.send_command.call_args_list)
    controller.send_command.reset_mock()
    controller.configure_sync(*repo.get_sync('other', 1))
    controller.load_file('two.mkv', 'Two')
    assert any('sub-delay=0.0,audio-delay=0.0' in str(call) for call in controller.send_command.call_args_list)


def subtitles():
    state = PlaybackState('film', 1, file_name='Film.S01E02.mkv')
    controller = SimpleNamespace(is_running=True, send_command=Mock())
    playback = SimpleNamespace(active_states={'film': state}, controllers={'film': controller}, tv=SimpleNamespace(state=None))
    return SubtitleService(playback), controller


@pytest.mark.asyncio
async def test_subdl_search_attach_archive_and_stale_selection(monkeypatch, tmp_path):
    service, controller = subtitles()
    monkeypatch.setenv('SUBDL_API_KEY', 'test-key')
    monkeypatch.setattr('backend.services.subtitles.get_data_dir', lambda: tmp_path)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('../../one.srt', SRT)
        z.writestr('two.ass', b'[Script Info]\n[Events]\nDialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,Hello')
    requests = []
    def respond(request):
        requests.append(request)
        if request.url.host == 'api.subdl.com':
            return httpx.Response(200, json={'status': True, 'subtitles': [
                {'language': 'RU', 'release_name': 'Release', 'url': '/subtitle/1-2.zip'}]})
        return httpx.Response(200, content=archive.getvalue())
    original = httpx.AsyncClient
    monkeypatch.setattr('backend.services.subtitles.httpx.AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    rows = await service.search('film', 1, title='Film', year=2020, season=1, episode=2)
    params = requests[0].url.params
    assert params['languages'] == 'RU,EN' and params['year'] == '2020'
    assert params['season_number'] == '1' and params['episode_number'] == '2'
    assert 'test-key' not in str(rows)
    controller.send_command.assert_not_called()
    files = await service.attach('film', 1, rows[0]['id'])
    assert len(files) == 2
    controller.send_command.assert_not_called()
    assert await service.attach('film', 1, files[0]['id']) == []
    command = controller.send_command.call_args.args[0]
    assert command[0] == 'sub-add' and command[2] == 'select'
    assert __import__('pathlib').Path(command[1]).parent == tmp_path / 'subtitles'
    service.playback.active_states['film'] = PlaybackState('film', 2)
    with pytest.raises(ValueError, match='изменилось'):
        await service.attach('film', 1, rows[0]['id'])


@pytest.mark.asyncio
async def test_missing_key_is_optional_and_files_are_validated(monkeypatch):
    monkeypatch.delenv('SUBDL_API_KEY', raising=False)
    service, controller = subtitles()
    with pytest.raises(ValueError, match='SUBDL_API_KEY'):
        await service.search('film', 1)
    controller.send_command.assert_not_called()
    assert service.validate(SRT) == '.srt'
    assert service.validate(SRT.decode().encode('utf-16')) == '.srt'
    assert service.validate(SRT + 'Привет'.encode('cp1251')) == '.srt'
    with pytest.raises(ValueError):
        service.validate(b'<html>Not a subtitle</html>')
