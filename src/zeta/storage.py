import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import cast


class JsonStore:
    """Single-process teaching store; transaction ownership stays with callers."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS documents ("
            "kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL, "
            "PRIMARY KEY(kind, id))"
        )
        self.connection.commit()

    @contextmanager
    def transaction(self) -> Generator[None]:
        with self.connection:
            yield

    def get(self, kind: str, key: str) -> str | None:
        row = self.connection.execute(
            "SELECT body FROM documents WHERE kind=? AND id=?", (kind, key)
        ).fetchone()
        return None if row is None else cast(str, row[0])

    def put(self, kind: str, key: str, body: str) -> None:
        self.connection.execute(
            "INSERT INTO documents(kind,id,body) VALUES(?,?,?) "
            "ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body",
            (kind, key, body),
        )

    def all(self, kind: str) -> list[str]:
        rows = self.connection.execute(
            "SELECT body FROM documents WHERE kind=? ORDER BY id", (kind,)
        ).fetchall()
        return [cast(str, row[0]) for row in rows]

    def close(self) -> None:
        self.connection.close()