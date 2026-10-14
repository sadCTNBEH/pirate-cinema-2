import tempfile
from pathlib import Path

from backend.repositories.db import Database
from backend.repositories.history import HistoryRepository


def test_history_entry_actions_are_scoped_to_single_episode():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db = Database(db_path=Path(tmp_dir) / "test.sqlite3")
        db.init_db()
        repository = HistoryRepository(db)

        repository.mark_played("hash-1", 1, "Show.S01E01.mkv")
        repository.mark_played("hash-1", 2, "Show.S01E02.mkv")
        repository.update_progress("hash-1", 1, timecode=120, duration=1200)

        assert repository.mark_watched("hash-1", 1) is True
        entries = repository.list_history()
        first_episode = next(entry for entry in entries if entry["file_index"] == 1)
        second_episode = next(entry for entry in entries if entry["file_index"] == 2)

        assert first_episode["is_watched"] == 1
        assert first_episode["playback_timecode"] == 1200
        assert second_episode["is_watched"] == 0

        assert repository.delete_entry("hash-1", 1) is True
        assert [entry["file_index"] for entry in repository.list_history()] == [2]
