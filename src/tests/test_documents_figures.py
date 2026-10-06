import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.database import document_store
from src.main import src as app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("src.routers.documents.UPLOAD_DIR", tmp_path)

    test_db_path = tmp_path / "document_registry.db"
    test_connection = sqlite3.connect(test_db_path, check_same_thread=False)
    test_connection.row_factory = sqlite3.Row
    test_connection.execute(
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
    test_connection.commit()
    monkeypatch.setattr(document_store, "DB_PATH", test_db_path)
    monkeypatch.setattr(document_store, "_connection", test_connection)

    yield TestClient(app)

    test_connection.close()


def test_upload_stores_figure_and_serves_it(client, monkeypatch):
    from src.services import parser

    class FakeImage:
        def save(self, path):
            Path(path).write_bytes(b"fakepng")

    def fake_convert(pdf_path):
        return ("# Paper\n\n![f](fig1.png)\n\nFigure 1: A curve.\n", {"fig1.png": FakeImage()})

    monkeypatch.setattr(parser, "marker_convert", fake_convert)
    monkeypatch.setattr("src.routers.documents.embed_text", lambda t: [0.1, 0.2])

    res = client.post(
        "/documents/", files={"file": ("paper.pdf", b"%PDF-fake", "application/pdf")}
    )
    assert res.status_code == 200
    doc_id = res.json()["document_id"]
    assert res.json()["chunks"] == 1  # the figure chunk

    served = client.get(f"/documents/{doc_id}/figures/fig1.png")
    assert served.status_code == 200
    assert served.content == b"fakepng"


def test_figure_name_traversal_is_rejected(client):
    res = client.get("/documents/any/figures/..%2F..%2Fetc%2Fpasswd")
    assert res.status_code in (404, 400)


def test_missing_figure_is_404(client):
    assert client.get("/documents/nope/figures/x.png").status_code == 404
