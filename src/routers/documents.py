import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from src.database import document_store
from src.database.vector_store import delete_chunks
from src.models.schemas import DocumentMeta, DocumentsListResponse
from src.services.ingest import ingest_document
from src.services.parser import PARSER_VERSION

router = APIRouter(prefix="/documents", tags=["Documents"])

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {".pdf", ".txt"}


def _process_document(
    document_id: str, file_path: Path, figures_dir: Path, filename: str
) -> None:
    """Parse, chunk, and embed an uploaded file. Runs as a background task
    (Starlette runs sync callables in its threadpool), so the slow,
    page-by-page vision calls never block the event loop."""

    def on_page_done(pages_done: int, total_pages: int) -> None:
        document_store.update_progress(document_id, f"page {pages_done}/{total_pages}")

    try:
        chunk_count = ingest_document(document_id, file_path, figures_dir, filename, on_page_done)
    except Exception as err:
        # Keep a record of the failed upload (with the reason) instead of
        # letting it vanish — the user can see it in the list and delete it.
        document_store.finalize_document(document_id, status="error", error_message=str(err))
        return

    document_store.finalize_document(
        document_id, status="ready", chunk_count=chunk_count, parser_version=PARSER_VERSION
    )


@router.post("/")
async def upload_document(file: UploadFile, background_tasks: BackgroundTasks):
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

    document_store.add_document(
        document_id=document_id,
        filename=filename,
        size_bytes=size_bytes,
        status="uploading",
    )
    figures_dir = doc_dir / "figures"
    background_tasks.add_task(_process_document, document_id, file_path, figures_dir, filename)

    return {
        "document_id": document_id,
        "filename": filename,
        "size_bytes": size_bytes,
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
                progress=row["progress"],
                created_at=row["created_at"],
            )
            for row in rows
        ]
    )


@router.get("/{document_id}/figures/{figure_name}")
def get_figure(document_id: str, figure_name: str):
    safe_name = Path(figure_name).name  # strip any path components
    figure_path = UPLOAD_DIR / document_id / "figures" / safe_name
    if not figure_path.is_file():
        raise HTTPException(status_code=404, detail=f"figure '{safe_name}' not found")
    return FileResponse(figure_path)


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
