from pathlib import Path

from src.services import ingest, parser


def test_ensure_fresh_noop_when_parser_version_current(monkeypatch, tmp_path):
    monkeypatch.setattr(
        ingest.document_store,
        "get_document",
        lambda doc_id: {"status": "ready", "parser_version": parser.PARSER_VERSION, "filename": "a.pdf"},
    )
    called = []
    monkeypatch.setattr(ingest, "ingest_document", lambda *a, **k: called.append(1))

    ingest.ensure_fresh("doc1", tmp_path)
    assert called == []


def test_ensure_fresh_noop_when_not_ready(monkeypatch, tmp_path):
    monkeypatch.setattr(
        ingest.document_store,
        "get_document",
        lambda doc_id: {"status": "uploading", "parser_version": None, "filename": "a.pdf"},
    )
    called = []
    monkeypatch.setattr(ingest, "ingest_document", lambda *a, **k: called.append(1))

    ingest.ensure_fresh("doc1", tmp_path)
    assert called == []


def test_ensure_fresh_noop_when_original_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        ingest.document_store,
        "get_document",
        lambda doc_id: {"status": "ready", "parser_version": None, "filename": "a.pdf"},
    )
    called = []
    monkeypatch.setattr(ingest, "ingest_document", lambda *a, **k: called.append(1))

    ingest.ensure_fresh("doc1", tmp_path)  # tmp_path/doc1/a.pdf doesn't exist
    assert called == []


def test_ensure_fresh_reparses_stale_document(monkeypatch, tmp_path):
    doc_dir = tmp_path / "doc1"
    doc_dir.mkdir()
    (doc_dir / "a.pdf").write_bytes(b"%PDF-fake")

    monkeypatch.setattr(
        ingest.document_store,
        "get_document",
        lambda doc_id: {"status": "ready", "parser_version": None, "filename": "a.pdf"},
    )
    calls = []
    monkeypatch.setattr(
        ingest,
        "ingest_document",
        lambda document_id, file_path, figures_dir, filename, on_page_done=None: (
            calls.append((document_id, file_path, figures_dir, filename)) or 3
        ),
    )
    finalized = []
    monkeypatch.setattr(
        ingest.document_store,
        "finalize_document",
        lambda document_id, **kwargs: finalized.append((document_id, kwargs)),
    )

    ingest.ensure_fresh("doc1", tmp_path)

    assert len(calls) == 1
    document_id, file_path, figures_dir, filename = calls[0]
    assert document_id == "doc1"
    assert file_path == doc_dir / "a.pdf"
    assert figures_dir == doc_dir / "figures"
    assert filename == "a.pdf"
    assert finalized == [
        ("doc1", {"status": "ready", "chunk_count": 3, "parser_version": parser.PARSER_VERSION})
    ]


def test_ensure_fresh_records_error_when_reparse_fails(monkeypatch, tmp_path):
    doc_dir = tmp_path / "doc1"
    doc_dir.mkdir()
    (doc_dir / "a.pdf").write_bytes(b"%PDF-fake")

    monkeypatch.setattr(
        ingest.document_store,
        "get_document",
        lambda doc_id: {"status": "ready", "parser_version": None, "filename": "a.pdf"},
    )

    def raise_err(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(ingest, "ingest_document", raise_err)
    finalized = []
    monkeypatch.setattr(
        ingest.document_store,
        "finalize_document",
        lambda document_id, **kwargs: finalized.append((document_id, kwargs)),
    )

    ingest.ensure_fresh("doc1", tmp_path)

    assert finalized == [("doc1", {"status": "error", "error_message": "boom"})]
