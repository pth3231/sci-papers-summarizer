import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from src.services.parser import parse_file
from src.services.chunker import chunk_text

from src.services.embedder import embed_text
from src.database.vector_store import add_chunk

router = APIRouter(prefix="/documents", tags=["Documents"])

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {".pdf", ".txt"}

@router.post("/")
async def upload_document(file: UploadFile = File(...)):
    filename = file.filename or "document"
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"unsupported file type '{extension}' — upload .pdf or .txt",
        )

    document_id = str(uuid.uuid4())

    file_path = UPLOAD_DIR / filename

    with file_path.open("wb") as buffer:
        buffer.write(await file.read())

    try:
        text = parse_file(str(file_path))
    except Exception as err:
        raise HTTPException(
            status_code=422, detail=f"could not parse '{filename}': {err}"
        ) from err

    chunks = chunk_text(text=text, document_id=document_id, chunk_size=1000, overlap=200)

    for chunk in chunks:
        embedding = embed_text(chunk.text)
        add_chunk(chunk_id=chunk.chunk_id, text=chunk.text, embedding=embedding, document_id=chunk.document_id, chunk_index=chunk.chunk_index)

    return {
        "document_id": document_id,
        "filename": filename,
        "characters": len(text),
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

@router.get("/")
def get_documents():
    return {"documents": []}