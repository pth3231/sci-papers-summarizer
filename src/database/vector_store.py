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


def search_chunks(
    query_embedding: list[float], top_k: int = 5, document_ids: list[str] | None = None
):
    return collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where={"document_id": {"$in": document_ids}} if document_ids else None,
    )


def delete_chunks(document_id: str):
    collection.delete(where={"document_id": document_id})
