import sqlite3
from contextlib import contextmanager
from typing import Generator

from backend.repositories.db import Database


class BaseRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        with self._db.get_connection() as conn:
            yield conn
