from contextlib import contextmanager

from backend.repositories.db import Database


class BaseRepository:
    def __init__(self, db: Database):
        self._db = db

    @contextmanager
    def connection(self):
        with self._db.get_connection() as conn:
            yield conn
