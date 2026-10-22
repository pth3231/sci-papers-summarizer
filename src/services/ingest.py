import shutil
from collections.abc import Callable
from pathlib import Path

from src.database import document_store
from src.database.vector_store import add_chunk, delete_chunks
from src.services.chunker import chunk_markdown
from src.services.embedder import embed_text
from src.services.parser import PARSER_VERSION, parse_file


def ingest_document(
    document_id: str,
    file_path: Path,
    figures_dir: Path,
    filename: str,
    on_page_done: Callable[[int, int], None] | None = None,
) -> int:
    """Parse, chunk, and embed `file_path`, replacing any chunks/figures
    already stored for `document_id`. Shared by the initial upload and by
    lazily re-parsing documents stale against PARSER_VERSION — both cases
    start from a clean slate rather than merging with whatever's already
    there, since a re-parse can produce a different chunk/figure count.
    """
    delete_chunks(document_id)
    shutil.rmtree(figures_dir, ignore_errors=True)

    parsed = parse_file(str(file_path), figures_dir=str(figures_dir), on_page_done=on_page_done)
    chunks = chunk_markdown(parsed.markdown, document_id=document_id)
    for chunk in chunks:
        add_chunk(
            chunk_id=chunk.chunk_id,
            text=chunk.text,
            embedding=embed_text(chunk.text),
            document_id=chunk.document_id,
            chunk_index=chunk.chunk_index,
            filename=filename,
            section=chunk.section,
            kind=chunk.kind,
            figure_path=chunk.figure_path,
        )
    return len(chunks)


def ensure_fresh(document_id: str, upload_dir: Path) -> None:
    """Re-parse `document_id` in place if its stored chunks came from an
    older PARSER_VERSION than the one currently running. No-op when the
    document is already current, missing, or not in a 'ready' state
    (uploading/error documents are left to their own upload flow).

    Meant to be called right before a document's chunks are used for
    retrieval — not on upload or on toggle — so re-parsing (which can be as
    slow as the original upload) only happens when it's actually needed.
    """
    doc = document_store.get_document(document_id)
    if doc is None or doc["status"] != "ready" or doc.get("parser_version") == PARSER_VERSION:
        return

    doc_dir = upload_dir / document_id
    file_path = doc_dir / doc["filename"]
    if not file_path.is_file():
        return  # original upload is gone — nothing to re-parse from

    try:
        chunk_count = ingest_document(document_id, file_path, doc_dir / "figures", doc["filename"])
    except Exception as err:
        document_store.finalize_document(document_id, status="error", error_message=str(err))
        return

    document_store.finalize_document(
        document_id, status="ready", chunk_count=chunk_count, parser_version=PARSER_VERSION
    )
