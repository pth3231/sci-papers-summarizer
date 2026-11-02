import json

from fastapi.testclient import TestClient

from src.main import src as app
from src.routers import chat as chat_router


async def _fake_stream_answer(system_prompt, user_prompt):
    yield "ok"


def test_selected_documents_send_full_text_not_a_topk_slice(monkeypatch):
    # The reported failure: summarizing a selected paper fed the model only a
    # few similarity-ranked chunks (abstract + a figure caption + a reference
    # fragment). With a document explicitly selected, the whole document's
    # text must reach the model instead of a tiny slice.
    search_calls = []
    full_calls = []
    full_result = {
        "documents": [[f"body chunk {i}" for i in range(30)]],
        "metadatas": [
            [{"document_id": "docA", "kind": "text", "chunk_index": i} for i in range(30)]
        ],
    }

    monkeypatch.setattr(chat_router, "require_api_key", lambda: "test-key")
    monkeypatch.setattr(chat_router, "embed_text", lambda text: [0.1, 0.2])
    monkeypatch.setattr(chat_router, "ensure_fresh", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        chat_router,
        "search_chunks",
        lambda **kwargs: search_calls.append(kwargs) or {"documents": [[]], "metadatas": [[]]},
    )
    monkeypatch.setattr(
        chat_router,
        "get_document_chunks",
        lambda ids: full_calls.append(ids) or full_result,
    )
    monkeypatch.setattr(chat_router, "stream_answer", _fake_stream_answer)

    res = TestClient(app).post(
        "/chat/", json={"message": "summarize", "top_k": 3, "document_ids": ["docA"]}
    )
    assert res.status_code == 200
    assert full_calls == [["docA"]]  # full-document fetch used
    assert search_calls == []  # similarity top_k slice NOT used when docs selected
    sources = json.loads(res.headers["X-Sources"])
    assert len(sources) == 30  # the whole document reached the model


def test_top_k_zero_skips_retrieval_entirely(monkeypatch):
    search_calls = []

    monkeypatch.setattr(chat_router, "require_api_key", lambda: "test-key")
    monkeypatch.setattr(chat_router, "embed_text", lambda text: [0.1, 0.2])
    monkeypatch.setattr(chat_router.document_store, "list_documents", lambda: [])
    monkeypatch.setattr(chat_router, "ensure_fresh", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        chat_router,
        "search_chunks",
        lambda **kwargs: search_calls.append(kwargs) or {"documents": [[]], "metadatas": [[]]},
    )
    monkeypatch.setattr(chat_router, "stream_answer", _fake_stream_answer)

    res = TestClient(app).post("/chat/", json={"message": "hi", "top_k": 0})
    assert res.status_code == 200
    assert search_calls == []  # top_k <= 0 must not call search_chunks at all
    assert res.headers["X-Sources"] == "[]"


def test_top_k_positive_still_retrieves(monkeypatch):
    search_calls = []

    monkeypatch.setattr(chat_router, "require_api_key", lambda: "test-key")
    monkeypatch.setattr(chat_router, "embed_text", lambda text: [0.1, 0.2])
    monkeypatch.setattr(chat_router.document_store, "list_documents", lambda: [])
    monkeypatch.setattr(chat_router, "ensure_fresh", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        chat_router,
        "search_chunks",
        lambda **kwargs: search_calls.append(kwargs) or {"documents": [[]], "metadatas": [[]]},
    )
    monkeypatch.setattr(chat_router, "stream_answer", _fake_stream_answer)

    res = TestClient(app).post("/chat/", json={"message": "hi", "top_k": 4})
    assert res.status_code == 200
    assert len(search_calls) == 1
    assert search_calls[0]["top_k"] == 4


def test_chat_lazily_reparses_in_scope_documents_before_retrieving(monkeypatch):
    reparsed = []

    monkeypatch.setattr(chat_router, "require_api_key", lambda: "test-key")
    monkeypatch.setattr(chat_router, "embed_text", lambda text: [0.1, 0.2])
    monkeypatch.setattr(chat_router, "ensure_fresh", lambda doc_id, upload_dir: reparsed.append(doc_id))
    monkeypatch.setattr(
        chat_router, "search_chunks", lambda **kwargs: {"documents": [[]], "metadatas": [[]]}
    )
    monkeypatch.setattr(
        chat_router, "get_document_chunks", lambda ids: {"documents": [[]], "metadatas": [[]]}
    )
    monkeypatch.setattr(chat_router, "stream_answer", _fake_stream_answer)

    res = TestClient(app).post(
        "/chat/", json={"message": "hi", "top_k": 4, "document_ids": ["docA", "docB"]}
    )
    assert res.status_code == 200
    assert reparsed == ["docA", "docB"]


def test_chat_reparses_all_ready_documents_when_no_scope_given(monkeypatch):
    reparsed = []

    monkeypatch.setattr(chat_router, "require_api_key", lambda: "test-key")
    monkeypatch.setattr(chat_router, "embed_text", lambda text: [0.1, 0.2])
    monkeypatch.setattr(
        chat_router.document_store,
        "list_documents",
        lambda: [
            {"id": "docA", "status": "ready"},
            {"id": "docB", "status": "uploading"},
        ],
    )
    monkeypatch.setattr(chat_router, "ensure_fresh", lambda doc_id, upload_dir: reparsed.append(doc_id))
    monkeypatch.setattr(
        chat_router, "search_chunks", lambda **kwargs: {"documents": [[]], "metadatas": [[]]}
    )
    monkeypatch.setattr(chat_router, "stream_answer", _fake_stream_answer)

    res = TestClient(app).post("/chat/", json={"message": "hi", "top_k": 4})
    assert res.status_code == 200
    assert reparsed == ["docA"]  # only the ready document, not the uploading one
