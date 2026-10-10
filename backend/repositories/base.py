from contextlib import contextmanager
from typing import Optional

from backend.repositories.db import Database, get_connection


class BaseRepository:
    def __init__(self, db: Optional[Database] = None):
        self._db = db

    @contextmanager
    def connection(self):
        if self._db is not None:
            with self._db.get_connection() as conn:
                yield conn
        else:
            with get_connection() as conn:
                yield conn
