import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from src.database import document_store
from src.database.vector_store import add_chunk, delete_chunks
from src.models.schemas import DocumentMeta, DocumentsListResponse
from src.services.chunker import chunk_text
from src.services.embedder import embed_text
from src.services.parser import parse_file

router = APIRouter(prefix="/documents", tags=["Documents"])

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {".pdf", ".txt"}


@router.post("/")
async def upload_document(file: UploadFile = File(...)):
    filename = Path(file.filename or "document").name
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"unsupported file type '{extension}' — upload .pdf or .txt",
        )

    document_id = str(uuid.uuid4())
    # Namespace each upload under its own document_id so two uploads of the
    # same filename never collide on disk or share a document record.
    doc_dir = UPLOAD_DIR / document_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    file_path = doc_dir / filename

    contents = await file.read()
    size_bytes = len(contents)
    with file_path.open("wb") as buffer:
        buffer.write(contents)

    try:
        text = parse_file(str(file_path))
        chunks = chunk_text(text=text, document_id=document_id, chunk_size=1000, overlap=200)
        for chunk in chunks:
            embedding = embed_text(chunk.text)
            add_chunk(
                chunk_id=chunk.chunk_id,
                text=chunk.text,
                embedding=embedding,
                document_id=chunk.document_id,
                chunk_index=chunk.chunk_index,
                filename=filename,
            )
    except Exception as err:
        # Keep a record of the failed upload (with the reason) instead of
        # letting it vanish — the user can see it in the list and delete it.
        document_store.add_document(
            document_id=document_id,
            filename=filename,
            size_bytes=size_bytes,
            status="error",
            chunk_count=0,
            error_message=str(err),
        )
        raise HTTPException(
            status_code=422, detail=f"could not parse '{filename}': {err}"
        ) from err

    document_store.add_document(
        document_id=document_id,
        filename=filename,
        size_bytes=size_bytes,
        status="ready",
        chunk_count=len(chunks),
    )

    return {
        "document_id": document_id,
        "filename": filename,
        "size_bytes": size_bytes,
        "chunks": len(chunks),
        "chunk_preview": [
            {
                "chunk_id": chunk.chunk_id,
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
            }
            for chunk in chunks[:3]
        ],
    }


@router.get("/", response_model=DocumentsListResponse)
def get_documents():
    rows = document_store.list_documents()
    return DocumentsListResponse(
        documents=[
            DocumentMeta(
                id=row["id"],
                filename=row["filename"],
                size_bytes=row["size_bytes"],
                status=row["status"],
                chunk_count=row["chunk_count"],
                error_message=row["error_message"],
                created_at=row["created_at"],
            )
            for row in rows
        ]
    )


@router.delete("/{document_id}")
def delete_document(document_id: str):
    existing = document_store.get_document(document_id)
    if existing is None:
        raise HTTPException(
            status_code=404, detail=f"document '{document_id}' not found"
        )

    # Registry row is removed last: if an earlier step throws, the record
    # stays and the delete is retryable instead of losing track of it.
    delete_chunks(document_id)
    shutil.rmtree(UPLOAD_DIR / document_id, ignore_errors=True)
    document_store.delete_document(document_id)

    return {"document_id": document_id, "deleted": True}
