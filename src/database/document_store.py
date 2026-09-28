import sqlite3
import threading
from pathlib import Path

DB_PATH = Path("./document_registry.db")

_lock = threading.Lock()
_connection = sqlite3.connect(DB_PATH, check_same_thread=False)
_connection.row_factory = sqlite3.Row

with _lock:
    _connection.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            status TEXT NOT NULL,
            error_message TEXT,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    _connection.commit()


def add_document(
    document_id: str,
    filename: str,
    size_bytes: int,
    status: str,
    chunk_count: int = 0,
    error_message: str | None = None,
) -> None:
    with _lock:
        _connection.execute(
            """
            INSERT INTO documents (id, filename, size_bytes, status, error_message, chunk_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (document_id, filename, size_bytes, status, error_message, chunk_count),
        )
        _connection.commit()


def list_documents() -> list[dict]:
    with _lock:
        rows = _connection.execute(
            "SELECT * FROM documents ORDER BY created_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def get_document(document_id: str) -> dict | None:
    with _lock:
        row = _connection.execute(
            "SELECT * FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
    return dict(row) if row else None


def delete_document(document_id: str) -> None:
    with _lock:
        _connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        _connection.commit()
