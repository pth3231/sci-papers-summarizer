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
            progress TEXT,
            parser_version INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    _connection.commit()
    for migration in (
        "ALTER TABLE documents ADD COLUMN progress TEXT",
        "ALTER TABLE documents ADD COLUMN parser_version INTEGER",
    ):
        try:
            # Migration for DBs created before this column existed.
            _connection.execute(migration)
            _connection.commit()
        except sqlite3.OperationalError:
            pass  # column already exists


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


def update_progress(document_id: str, progress: str) -> None:
    with _lock:
        _connection.execute(
            "UPDATE documents SET progress = ? WHERE id = ?", (progress, document_id)
        )
        _connection.commit()


def finalize_document(
    document_id: str,
    status: str,
    chunk_count: int = 0,
    error_message: str | None = None,
    parser_version: int | None = None,
) -> None:
    """`parser_version`, when given, records which parser produced the
    current chunks — left untouched (via COALESCE) on error finalizes,
    where the previous chunks (if any) are still what's stored."""
    with _lock:
        _connection.execute(
            """
            UPDATE documents
            SET status = ?, chunk_count = ?, error_message = ?, progress = NULL,
                parser_version = COALESCE(?, parser_version)
            WHERE id = ?
            """,
            (status, chunk_count, error_message, parser_version, document_id),
        )
        _connection.commit()
