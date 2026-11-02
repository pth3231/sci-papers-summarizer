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


def test_search_reserves_text_slots_even_when_figures_score_higher(store):
    # Reproduces the real failure mode: a question about the paper's
    # tasks/methods/results should still come back with that body text, even
    # if a couple of sparse figure-caption chunks happen to score closer to
    # the query embedding than any single text chunk.
    query = [1.0, 0.0, 0.0]
    store.add_chunk(
        "fig1", "Figure 1: result", [0.99, 0.0, 0.0], "d1", 0, kind="figure"
    )
    store.add_chunk(
        "fig2", "Figure 2", [0.98, 0.0, 0.0], "d1", 1, kind="figure"
    )
    store.add_chunk(
        "methods", "The method trains a classifier on...", [0.5, 0.5, 0.0], "d1", 2, kind="text"
    )
    store.add_chunk(
        "results", "Results show a 10% improvement...", [0.4, 0.6, 0.0], "d1", 3, kind="text"
    )

    res = store.search_chunks(
        query, top_k=3, document_ids=["d1"], reserves={"text": 0.6}
    )
    ids = res["ids"][0]
    kinds = [m["kind"] for m in res["metadatas"][0]]

    assert "methods" in ids and "results" in ids  # body text wasn't crowded out
    assert kinds.count("text") >= 2


def test_search_reserves_multiple_kinds_independently(store):
    # Guaranteeing a share for "text" and a separate share for "reference"
    # at once must not let either one steal the other's reserved slots.
    query = [1.0, 0.0, 0.0]
    store.add_chunk("fig1", "Figure 1: result", [0.99, 0.0, 0.0], "d1", 0, kind="figure")
    store.add_chunk("fig2", "Figure 2", [0.98, 0.0, 0.0], "d1", 1, kind="figure")
    store.add_chunk(
        "methods", "The method trains a classifier on...", [0.5, 0.5, 0.0], "d1", 2, kind="text"
    )
    store.add_chunk(
        "ref1", "[1] Some Author. Some Paper.", [0.4, 0.6, 0.0], "d1", 3, kind="reference"
    )

    res = store.search_chunks(
        query, top_k=4, document_ids=["d1"], reserves={"text": 0.25, "reference": 0.25}
    )
    ids = res["ids"][0]
    assert "methods" in ids
    assert "ref1" in ids


def test_search_without_reserve_is_a_plain_pooled_search(store):
    store.add_chunk("fig1", "Figure 1: result", [0.99, 0.0, 0.0], "d1", 0, kind="figure")
    store.add_chunk("methods", "The method trains a classifier on...", [0.5, 0.5, 0.0], "d1", 1, kind="text")

    res = store.search_chunks([1.0, 0.0, 0.0], top_k=1, document_ids=["d1"])
    assert res["ids"][0] == ["fig1"]  # no reservation requested: pure nearest-neighbor


def test_get_document_chunks_returns_whole_document_text_first(store):
    # The stored chunks interleave body text and figures in reading order;
    # whole-document context wants all textual content first, then figures
    # appended, so the model sees the full prose before any image blocks.
    store.add_chunk("t0", "intro", [0.1, 0.0], "d1", 0, kind="text")
    store.add_chunk("f0", "![p0](p0.png)", [0.2, 0.0], "d1", 1, kind="figure", figure_path="p0.png")
    store.add_chunk("t1", "methods", [0.3, 0.0], "d1", 2, kind="text")
    store.add_chunk("r0", "[1] A ref", [0.4, 0.0], "d1", 3, kind="reference")

    res = store.get_document_chunks(["d1"])
    docs = res["documents"][0]
    kinds = [m["kind"] for m in res["metadatas"][0]]

    assert len(docs) == 4  # the whole document, nothing dropped
    assert kinds == ["text", "reference", "figure"] or kinds == ["text", "text", "reference", "figure"] \
        or kinds[-1] == "figure"  # figures appended last
    # textual chunks preserve document order, figures come after all text
    assert docs[-1] == "![p0](p0.png)"
    assert docs.index("intro") < docs.index("methods") < docs.index("![p0](p0.png)")


def test_get_document_chunks_orders_by_document_then_position(store):
    store.add_chunk("d2c1", "second doc body", [0.1, 0.0], "d2", 1, kind="text")
    store.add_chunk("d1c0", "first doc body", [0.2, 0.0], "d1", 0, kind="text")

    res = store.get_document_chunks(["d1", "d2"])
    docs = res["documents"][0]
    assert docs.index("first doc body") < docs.index("second doc body")
