"""Existing history/collection HTTP routes against persistent SQLite."""
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock

from backend.api import deps
from backend.api.routers.history import history_router
from backend.api.routers.collections import collections_router
from backend.repositories.db import Database
from backend.repositories.history import HistoryRepository
from backend.repositories.collections import CollectionRepository
from backend.services.history import HistoryService
from backend.services.collections import CollectionService


def client_for(path):
    db = Database(path)
    db.init_db()
    history = HistoryRepository(db)
    meta = {'id':'shikimori:42361','shikimori_id':42361,'title':'Nagatoro','type':'series','year':2021}
    provider = SimpleNamespace(cards={'390':'https://animego.online/390-title.html'},
        catalog_card=AsyncMock(return_value={'anime_id':'390','episodes':[{'number':3},{'number':4}]}),
        catalog=AsyncMock(return_value={'anime_id':'390'}))
    app = FastAPI()
    app.include_router(history_router)
    app.include_router(collections_router)
    app.dependency_overrides[deps.get_history_service] = lambda: HistoryService(history)
    app.dependency_overrides[deps.get_collection_service] = lambda: CollectionService(CollectionRepository(db))
    app.dependency_overrides[deps.get_metadata_service] = lambda: SimpleNamespace(movie_meta=AsyncMock(return_value=meta))
    app.dependency_overrides[deps.get_online_service] = lambda: SimpleNamespace(get_provider=lambda name: provider)
    return TestClient(app), history, db


def test_unified_history_restart_resume_and_switch_source(tmp_path):
    path = tmp_path / 'history.sqlite3'
    client, repo, db = client_for(path)
    item = {'media_id':'yummy:947','title':'Nagatoro','media_type':'series'}
    assert client.put('/api/collections/watch_later/yummy:947',json=item).status_code == 200
    assert client.get('/api/history').json() == []
    assert client.get('/api/collections/watch_later').json()[0]['media_id'] == 'shikimori:42361'
    request = {'media_id':'shikimori:42361','source':'animego','source_title_id':'390','episode':3,'player':'CVH','voice_id':'0'}
    response = client.post('/api/history/anime',json=request)
    assert response.status_code == 200, response.text
    assert not response.json()['is_watched']
    assert response.json()['episode'] == 3
    # New app, DB connection and services: no memory state survives.
    client.close()
    client, repo, db = client_for(path)
    resume = client.get('/api/history/continue').json()
    assert len(resume) == 1 and resume[0]['episode'] == 3
    assert resume[0]['playback_timecode'] == 0
    context = resume[0]['anime_playback']
    assert context['card_media_id'] == 'shikimori:42361' and context['source_title_id'] == '390'
    assert client.post('/api/history/anime',json=dict(request,episode=4)).status_code == 200
    assert client.post('/api/history/anime',json=dict(request,source='yummy',source_title_id='947',episode=4,voice='AniLibria')).status_code == 200
    items = client.get('/api/history').json()
    assert len(items) == 1 and items[0]['episode'] == 4
    assert items[0]['anime_playback']['source'] == 'yummy'
    assert items[0]['anime_playback']['voice'] == 'AniLibria'
    latest = client.get('/api/history/anime/shikimori:42361').json()
    assert latest['source'] == 'yummy' and latest['episode'] == 4 and latest['voice'] == 'AniLibria'
    assert client.put('/api/collections/watch_later/shikimori:42361',json=dict(item,media_id='shikimori:42361')).status_code == 200
    assert len(client.get('/api/collections/watch_later').json()) == 1
    assert client.delete('/api/collections/watch_later/yummy:947').status_code == 200
    assert client.get('/api/collections/watch_later').json() == []
    key = items[0]['torrent_hash']
    assert client.post(f'/api/history/{key}/0/watched').status_code == 200
    assert client.get('/api/history/continue').json() == []
    assert client.delete(f'/api/history/{key}/0').status_code == 200
    assert client.get('/api/history').json() == []


def test_completion_marks_episode_even_after_auto_next_without_overwriting_resume(tmp_path):
    client, repo, db = client_for(tmp_path / 'completion.sqlite3')
    request = {'media_id':'shikimori:42361','source':'animego','source_title_id':'390','episode':3,'player':'CVH'}
    assert client.post('/api/history/anime',json=request).status_code == 200
    assert client.post('/api/history/anime/complete',json=request).status_code == 200
    assert client.get('/api/history').json()[0]['is_watched']
    assert client.post('/api/history/anime',json=dict(request,episode=4)).status_code == 200
    # A late or duplicate completion from episode 3 cannot mark episode 4.
    assert client.post('/api/history/anime/complete',json=dict(request,source='yummy',source_title_id='947')).status_code == 200
    latest=client.get('/api/history').json()[0]
    assert latest['episode']==4 and not latest['is_watched']
    with db.get_connection() as conn:
        watched=conn.execute('SELECT title_id,season,episode,is_watched FROM media_episode_history').fetchall()
    assert [tuple(row) for row in watched]==[('shikimori:42361',1,3,1)]


def test_migration_and_normal_movie_progress_unchanged(tmp_path):
    path = tmp_path / 'old.sqlite3'
    db = Database(path); db.init_db()
    with db.get_connection() as conn:
        conn.execute('ALTER TABLE media_file_history DROP COLUMN playback_context')
    # Idempotent, additive migration for pre-existing databases.
    db.init_db(); db.init_db()
    repo = HistoryRepository(db)
    repo.mark_played('moviehash',0,'Movie.mkv')
    repo.update_progress('moviehash',0,120,3600)
    client, _, _ = client_for(path)
    assert client.get('/api/history/continue').json()[0]['playback_timecode'] == 120
    assert client.get('/api/history').json()[0]['anime_playback'] is None
    repo.mark_played('zero',0,'Not started.mkv')
    assert len(client.get('/api/history/continue').json()) == 1


def test_different_season_is_not_merged_by_similar_name(tmp_path):
    client, repo, _ = client_for(tmp_path / 'history.sqlite3')
    base = {'media_id':'shikimori:42361','card_media_id':'shikimori:42361','source':'animego','source_title_id':'390',
        'title':'Nagatoro','season':1,'episode':3}
    repo.save_anime_playback(base)
    repo.save_anime_playback(dict(base,media_id='shikimori:50197',card_media_id='shikimori:50197',source_title_id='1235',title='Nagatoro 2'))
    assert len(client.get('/api/history').json()) == 2


def test_source_identity_without_shikimori_and_no_fake_torrent(tmp_path):
    from backend.repositories.library import LibraryRepository
    client, repo, db = client_for(tmp_path / 'history.sqlite3')
    client.app.dependency_overrides[deps.get_metadata_service] = lambda: SimpleNamespace(movie_meta=AsyncMock(return_value={
        'id':'yummy:947','title':'Source-only title','type':'series'}))
    request = {'media_id':'yummy:947','source':'yummy','source_title_id':'947','episode':3}
    for episode in (3,4):
        response = client.post('/api/history/anime',json=dict(request,episode=episode))
        assert response.status_code == 200, response.text
    items = client.get('/api/history').json()
    assert len(items) == 1 and items[0]['imdb_id'] == 'yummy:947'
    assert items[0]['episode'] == 4
    assert LibraryRepository(db).count_library() == 0
