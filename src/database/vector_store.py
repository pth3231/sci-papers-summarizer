import chromadb

client = chromadb.PersistentClient(path="./chroma_db")
# v2: extended chunk metadata (section/kind/figure_path). The old
# "documents" collection is orphaned — documents must be re-uploaded.
collection = client.get_or_create_collection(name="documents_v2")


def add_chunk(
    chunk_id: str,
    text: str,
    embedding: list[float],
    document_id: str,
    chunk_index: int,
    filename: str | None = None,
    section: str = "",
    kind: str = "text",
    figure_path: str | None = None,
):
    metadata = {
        "document_id": document_id,
        "chunk_index": chunk_index,
        "section": section,
        "kind": kind,
    }
    if filename is not None:
        metadata["filename"] = filename
    if figure_path is not None:
        metadata["figure_path"] = figure_path
    collection.add(
        ids=[chunk_id], documents=[text], embeddings=[embedding], metadatas=[metadata]
    )


def _rows(result) -> list[tuple]:
    """Flatten one query() result's nested single-query lists into
    (id, document, metadata, distance) row tuples."""
    if not result or not result.get("ids") or not result["ids"][0]:
        return []
    return list(
        zip(
            result["ids"][0],
            result["documents"][0],
            result["metadatas"][0],
            result["distances"][0],
        )
    )


def _rows_to_result(rows: list[tuple]):
    ids, documents, metadatas, distances = zip(*rows) if rows else ((), (), (), ())
    return {
        "ids": [list(ids)],
        "documents": [list(documents)],
        "metadatas": [list(metadatas)],
        "distances": [list(distances)],
    }


def search_chunks(
    query_embedding: list[float],
    top_k: int = 5,
    document_ids: list[str] | None = None,
    reserves: dict[str, float] | None = None,
):
    """Pooled similarity search, with an optional reserved share of the
    budget guaranteed to one or more chunk kinds (e.g. {"text": 0.6})
    regardless of how they rank against other kinds. A figure/caption or
    references-list chunk often carries little explanatory text relative to
    the paper's actual prose (see parser.py's graceful-degradation fallback
    and chunker.py's references-section tagging), so a pure similarity
    search can let a handful of them outscore real body text and crowd it
    out of the context window entirely. Callers that want that guarantee
    (the chat RAG flow) pass `reserves`; callers that want a plain pooled
    search (e.g. the raw /search endpoint) leave it unset. Multiple kinds
    may each reserve their own share — each is queried independently, and
    only the first match of a chunk that satisfies more than one reserved
    kind's filter is kept (`kind` is a single value per chunk, so this is
    purely about not double-counting the same id in the budget).
    """
    if top_k <= 0:
        return _rows_to_result([])

    base_filter = {"document_id": {"$in": document_ids}} if document_ids else None

    def query(where, n_results):
        return collection.query(
            query_embeddings=[query_embedding], n_results=n_results, where=where
        )

    if not reserves:
        return _rows_to_result(_rows(query(base_filter, top_k)))

    reserved_rows: list[tuple] = []
    selected_ids: set[str] = set()
    total_reserved_n = 0
    for kind, share in reserves.items():
        if share <= 0:
            continue
        reserve_filter = {"kind": kind}
        if base_filter:
            reserve_filter = {"$and": [base_filter, reserve_filter]}
        reserved_n = max(1, round(top_k * share))
        total_reserved_n += reserved_n
        for row in _rows(query(reserve_filter, reserved_n)):
            if row[0] not in selected_ids:
                selected_ids.add(row[0])
                reserved_rows.append(row)

    remaining = top_k - len(reserved_rows)
    fill_rows: list[tuple] = []
    if remaining > 0:
        # Over-fetch so enough non-duplicate candidates remain after the
        # reserved rows already claimed above are filtered back out.
        pooled_rows = _rows(query(base_filter, top_k + total_reserved_n))
        fill_rows = [row for row in pooled_rows if row[0] not in selected_ids][:remaining]

    merged = sorted(reserved_rows + fill_rows, key=lambda row: row[3])[:top_k]
    return _rows_to_result(merged)


def get_document_chunks(document_ids: list[str]):
    """Return every stored chunk for the given documents, ordered for
    full-document context rather than similarity: all textual chunks first
    (text/reference, in document then chunk_index order), with figure chunks
    appended after. Used by the chat flow when the user has explicitly
    selected papers, so the model receives the whole paper's prose instead of
    a handful of similarity-ranked excerpts that can miss most of the body.
    Returns the same shape as `search_chunks` so callers are interchangeable.
    """
    if not document_ids:
        return _rows_to_result([])

    result = collection.get(where={"document_id": {"$in": document_ids}})
    ids = result.get("ids") or []
    documents = result.get("documents") or []
    metadatas = result.get("metadatas") or []

    doc_order = {doc_id: i for i, doc_id in enumerate(document_ids)}

    def sort_key(item):
        meta = item[2]
        return (
            meta.get("kind") == "figure",  # False (text/reference) sorts before True (figures)
            doc_order.get(meta.get("document_id"), len(doc_order)),
            meta.get("chunk_index", 0),
        )

    # No distances for a non-similarity fetch; carry None so the row shape
    # still matches _rows()/_rows_to_result.
    rows = sorted(zip(ids, documents, metadatas, [None] * len(ids)), key=sort_key)
    return _rows_to_result(rows)


def delete_chunks(document_id: str):
    collection.delete(where={"document_id": document_id})
