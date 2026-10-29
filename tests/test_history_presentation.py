from backend.api.schemas.history import FileHistoryEntry, HistoryItemResponse
from backend.repositories.db import Database
from backend.repositories.history import HistoryRepository
from backend.repositories.metadata import MetadataRepository


def test_history_and_continue_return_canonical_title_and_poster(tmp_path, monkeypatch):
    monkeypatch.setattr('backend.repositories.history.get_data_dir', lambda: tmp_path)
    database = Database(db_path=tmp_path / 'history.sqlite')
    database.init_db()
    history, metadata = HistoryRepository(database), MetadataRepository(database)
    metadata.save_full_metadata('torrent', 'Film.S01E02.1080p', '', 2020, 7, '', '[]', imdb_id='tt123')
    metadata.save_cached_metadata('tt123', {'title_ru': 'Понятное название', 'poster_url': 'https://poster.test/image.jpg'}, imdb_id='tt123')
    history.mark_played('torrent', 1, 'Film.S01E02.1080p.mkv')
    history.update_progress('torrent', 1, 120, 1800)
    for row, schema in ((history.list_history()[0], HistoryItemResponse),
                        (history.list_continue_watching()[0], FileHistoryEntry)):
        assert row['title'] == 'Понятное название'
        assert row['imdb_id'] == 'tt123'
        assert schema.model_validate(row).poster_url == 'https://poster.test/image.jpg'
        assert row['file_name'] == 'Film.S01E02.1080p.mkv'


def test_catalog_poster_is_reused_and_launch_does_not_overwrite_title(tmp_path, monkeypatch):
    monkeypatch.setattr('backend.repositories.history.get_data_dir', lambda: tmp_path)
    database = Database(db_path=tmp_path / 'history.sqlite')
    database.init_db()
    history, metadata = HistoryRepository(database), MetadataRepository(database)
    metadata.save_full_metadata('torrent', 'Название фильма', '', 2020, 7, '', '[]', imdb_id='tt123')
    metadata.save_metadata_title('torrent', 'File.Release.1080p.mkv')
    history.mark_played('torrent', 1, 'File.Release.1080p.mkv')
    directory = tmp_path / 'posters' / 'catalog'
    directory.mkdir(parents=True)
    (directory / 'tt123.jpg').write_bytes(b'fixture')
    row = history.list_history()[0]
    assert row['title'] == 'Название фильма'
    assert row['poster_url'] == '/api/posters/catalog/tt123.jpg'


def test_file_name_fallback_is_clean_and_canonical_punctuation_is_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr('backend.repositories.history.get_data_dir', lambda: tmp_path)
    database = Database(db_path=tmp_path / 'history.sqlite')
    database.init_db()
    history, metadata = HistoryRepository(database), MetadataRepository(database)
    history.mark_played('torrent', 1, 'Show.Name.S02E03.1080p.WEB-DL.mkv')
    assert history.list_history()[0]['title'] == 'Show Name'
    metadata.save_full_metadata('torrent', 'release', '', 2020, 7, '', '[]', imdb_id='tt123')
    metadata.save_cached_metadata('tt123', {'title': '2001: A Space/Odyssey'}, imdb_id='tt123')
    assert history.list_history()[0]['title'] == '2001: A Space/Odyssey'
