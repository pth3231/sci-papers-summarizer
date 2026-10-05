import pytest

from src.database import vector_store


@pytest.fixture()
def store(tmp_path, monkeypatch):
    import chromadb

    client = chromadb.PersistentClient(path=str(tmp_path))
    collection = client.get_or_create_collection(name="documents_v2")
    monkeypatch.setattr(vector_store, "collection", collection)
    return vector_store


def test_collection_name_is_v2(store):
    assert store.collection.name == "documents_v2"


def test_add_chunk_persists_extended_metadata(store):
    store.add_chunk(
        chunk_id="c1", text="t", embedding=[0.1, 0.2], document_id="d1",
        chunk_index=0, filename="p.pdf", section="Methods", kind="figure",
        figure_path="figures/f1.png",
    )
    got = store.collection.get(ids=["c1"])
    meta = got["metadatas"][0]
    assert meta["section"] == "Methods"
    assert meta["kind"] == "figure"
    assert meta["figure_path"] == "figures/f1.png"


def test_search_scopes_by_document_ids(store):
    store.add_chunk("a", "alpha", [1.0, 0.0], "d1", 0, filename="a.pdf")
    store.add_chunk("b", "beta", [0.0, 1.0], "d2", 0, filename="b.pdf")
    res = store.search_chunks([1.0, 0.0], top_k=2, document_ids=["d2"])
    ids = res["ids"][0]
    assert ids == ["b"]
