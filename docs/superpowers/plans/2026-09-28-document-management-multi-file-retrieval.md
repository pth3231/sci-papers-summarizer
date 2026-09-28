# Document Management & Multi-File Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the document list into a real, backend-persisted registry; let users scope chat retrieval to any custom subset of uploaded papers; add document deletion; and show which excerpts each answer drew from.

**Architecture:** A new SQLite-backed document registry (`src/database/document_store.py`) becomes the source of truth for what's been uploaded, replacing the current empty stub and local-only frontend state. Retrieval (`vector_store.search_chunks`) gains a `document_ids` filter using Chroma's `$in` operator. The chat endpoint computes retrieved sources before streaming and attaches them as a JSON response header (`X-Sources`) rather than changing the streamed body format. The frontend switches from a single-select "focus" toggle to multi-select checkboxes and fetches the document list from the backend on load instead of starting empty.

**Tech Stack:** FastAPI + Pydantic + chromadb + stdlib `sqlite3` (backend); React 19 + TypeScript (frontend). No new dependencies.

## Global Constraints

- No new backend or frontend dependencies — `sqlite3` is stdlib; `fastapi[standard]` already provides `httpx`, which `fastapi.testclient.TestClient` uses.
- Multi-document retrieval returns one **global top-k across all selected documents combined** — not top-k per document.
- Uploads stay **synchronous** — no background job queue or polling this round.
- Same-name uploads must never collide: each upload is saved under `uploads/<document_id>/<filename>`, never `uploads/<filename>`.
- Delete order is Chroma chunks → disk folder → registry row, in that order — the registry row is removed **last** so a failed step leaves a retryable record instead of orphaned data.
- Source excerpts are display-only, truncated to 200 characters — never re-parsed for grounding.
- CORS must add `expose_headers=["X-Sources"]` or browsers will hide the header from cross-origin `fetch` calls in dev.
- **No automated test framework this round** (explicit decision, see spec's Non-goals). Every task instead has a manual verification step using `fastapi.testclient.TestClient` in an ad-hoc script (no test files created) or, for frontend/UI behavior, a real browser check. Backend verification scripts run with cwd at `src/` (the directory containing `pyproject.toml`), matching how `vector_store.py`'s `./chroma_db` and `documents.py`'s `uploads` already resolve relative to the process's working directory at runtime.
- **There are two `pyproject.toml` files** — one at the repo root (`package = false`, "run directly") and one inside `src/` (the one with the real `.venv`, actually used to run this app — confirmed by `uv run fastapi dev` from `src/` auto-discovering `src.main:src` and serving successfully). `uv run fastapi dev`/`fastapi run` do their own package-root sys.path detection, so they work unmodified from `src/`. A bare `uv run python -c "..."` does **not** do that detection, so every verification script in this plan starts with `import sys; sys.path.insert(0, '..')` before any `from src...` import — this is required, not optional; omitting it fails with `ModuleNotFoundError: No module named 'src'`.
- Spec reference: `docs/superpowers/specs/2026-09-28-document-management-multi-file-retrieval-design.md`.

---

### Task 1: Document registry module

**Files:**
- Create: `src/database/document_store.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nothing (foundational module).
- Produces (used by Tasks 4 and 9):
  - `add_document(document_id: str, filename: str, size_bytes: int, status: str, chunk_count: int = 0, error_message: str | None = None) -> None`
  - `list_documents() -> list[dict]` — each dict has keys `id, filename, size_bytes, status, error_message, chunk_count, created_at`, ordered newest first.
  - `get_document(document_id: str) -> dict | None`
  - `delete_document(document_id: str) -> None`

- [ ] **Step 1: Create the document registry module**

Create `src/database/document_store.py`:

```python
import sqlite3
import threading
from pathlib import Path

DB_PATH = Path("./document_registry.db")

_lock = threading.Lock()
_connection = sqlite3.connect(DB_PATH, check_same_thread=False)
_connection.row_factory = sqlite3.Row

with _lock:
    _connection.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            status TEXT NOT NULL,
            error_message TEXT,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    _connection.commit()


def add_document(
    document_id: str,
    filename: str,
    size_bytes: int,
    status: str,
    chunk_count: int = 0,
    error_message: str | None = None,
) -> None:
    with _lock:
        _connection.execute(
            """
            INSERT INTO documents (id, filename, size_bytes, status, error_message, chunk_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (document_id, filename, size_bytes, status, error_message, chunk_count),
        )
        _connection.commit()


def list_documents() -> list[dict]:
    with _lock:
        rows = _connection.execute(
            "SELECT * FROM documents ORDER BY created_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def get_document(document_id: str) -> dict | None:
    with _lock:
        row = _connection.execute(
            "SELECT * FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
    return dict(row) if row else None


def delete_document(document_id: str) -> None:
    with _lock:
        _connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        _connection.commit()
```

This mirrors `src/database/vector_store.py`'s convention of doing setup as top-level module code (no explicit `init()` call needed from `main.py`). `check_same_thread=False` plus the module-level `threading.Lock()` around every statement makes the single shared connection safe to use from FastAPI's threadpool-executed sync routes.

- [ ] **Step 2: Ignore the runtime database file**

Modify `.gitignore` — add `document_registry.db*` (the `*` also covers SQLite's `-journal`/`-wal` sidecar files) next to the existing `chroma_db/` and `uploads/` entries:

```
node_modules
.venv
__pycache__
chroma_db/
uploads/
document_registry.db*
.env
```

- [ ] **Step 3: Verify manually**

Run from the `src/` directory (where `pyproject.toml` and the venv live):

```bash
cd src
uv run python -c "
import sys
sys.path.insert(0, '..')

from src.database import document_store as ds

ds.add_document('test-doc-1', 'sample.pdf', 1234, 'ready', chunk_count=3)
docs = ds.list_documents()
assert any(d['id'] == 'test-doc-1' for d in docs), docs

fetched = ds.get_document('test-doc-1')
assert fetched is not None and fetched['filename'] == 'sample.pdf', fetched

ds.delete_document('test-doc-1')
assert ds.get_document('test-doc-1') is None

print('document_store OK')
"
```

Expected output: `document_store OK` with no `AssertionError`. This creates `src/document_registry.db` — leave it in place, it's gitignored.

- [ ] **Step 4: Commit**

```bash
git add src/database/document_store.py .gitignore
git commit -m "feat: add SQLite document registry"
```

---

### Task 2: Multi-document retrieval filtering

**Files:**
- Modify: `src/database/vector_store.py`
- Modify: `src/models/schemas.py:3-5` (`SearchRequest`)
- Modify: `src/routers/search.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces (used by Tasks 3, 4, 9):
  - `search_chunks(query_embedding: list[float], top_k: int = 5, document_ids: list[str] | None = None) -> dict` — same Chroma result shape as before, now filtered to the given document IDs when the list is non-empty.
  - `delete_chunks(document_id: str) -> None`
  - `SearchRequest.document_ids: list[str] | None = None`

- [ ] **Step 1: Update `vector_store.py`**

Replace the full contents of `src/database/vector_store.py`:

```python
import chromadb

client = chromadb.PersistentClient(path="./chroma_db")
collection = client.get_or_create_collection(name="documents")

def add_chunk(chunk_id: str, text: str, embedding: list[float], document_id: str, chunk_index: int, filename: str | None = None):
    metadata = {
        "document_id": document_id,
        "chunk_index": chunk_index,
    }
    if filename is not None:
        metadata["filename"] = filename
    collection.add(ids=[chunk_id], documents=[text], embeddings=[embedding],
        metadatas=[metadata],
    )

def search_chunks(query_embedding: list[float], top_k: int = 5, document_ids: list[str] | None = None):
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where={"document_id": {"$in": document_ids}} if document_ids else None,
    )
    return results

def delete_chunks(document_id: str):
    collection.delete(where={"document_id": document_id})
```

- [ ] **Step 2: Add `document_ids` to `SearchRequest`**

Modify `src/models/schemas.py` — change the `SearchRequest` class:

```python
class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    document_ids: list[str] | None = None
```

- [ ] **Step 3: Pass `document_ids` through the search route**

Modify `src/routers/search.py` — update the `search` function body:

```python
@router.post("/", response_model=SearchResponse)
def search(request: SearchRequest):
    query_embedding = embed_text(request.query)

    results = search_chunks(
        query_embedding=query_embedding,
        top_k=request.top_k,
        document_ids=request.document_ids,
    )

    search_results = []

    documents = results["documents"][0]
    distances = results["distances"][0]

    for text, distance in zip(documents, distances):
        search_results.append(SearchResult(text=text, score=distance))

    return SearchResponse(results=search_results)
```

- [ ] **Step 4: Verify manually**

```bash
cd src
uv run python -c "
import sys
sys.path.insert(0, '..')

from fastapi.testclient import TestClient
from src.main import src as app
from src.database import vector_store as vs
from src.services.embedder import embed_text

client = TestClient(app)

vs.add_chunk(chunk_id='verify-chunk-1', text='hello world', embedding=embed_text('hello world'), document_id='verify-doc-a', chunk_index=0, filename='a.txt')
vs.add_chunk(chunk_id='verify-chunk-2', text='goodbye world', embedding=embed_text('goodbye world'), document_id='verify-doc-b', chunk_index=0, filename='b.txt')

scoped = client.post('/search/', json={'query': 'hello', 'top_k': 5, 'document_ids': ['verify-doc-a']})
assert scoped.status_code == 200, scoped.text
scoped_results = scoped.json()['results']
assert len(scoped_results) == 1 and scoped_results[0]['text'] == 'hello world', scoped_results

everything = client.post('/search/', json={'query': 'hello', 'top_k': 5})
assert len(everything.json()['results']) >= 2, everything.json()

vs.delete_chunks('verify-doc-a')
vs.delete_chunks('verify-doc-b')
after = vs.search_chunks(query_embedding=embed_text('hello world'), top_k=5, document_ids=['verify-doc-a'])
assert after['documents'][0] == [], after

print('search endpoint OK')
"
```

Expected output: `search endpoint OK`.

- [ ] **Step 5: Commit**

```bash
git add src/database/vector_store.py src/models/schemas.py src/routers/search.py
git commit -m "feat: filter retrieval by a custom set of document IDs"
```

---

### Task 3: Chat sources and multi-document scoping

**Files:**
- Modify: `src/models/schemas.py` (`ChatRequest`)
- Modify: `src/routers/chat.py`
- Modify: `src/main.py:27-32` (CORS middleware)

**Interfaces:**
- Consumes: `search_chunks(query_embedding, top_k, document_ids)` from Task 2.
- Produces (used by Tasks 5, 9):
  - `ChatRequest.document_ids: list[str] | None = None` (replaces `document_id`).
  - `POST /chat/` response carries an `X-Sources` header: a JSON array of `{"filename": str, "excerpt": str}`, computed before the answer stream begins.

- [ ] **Step 1: Replace `document_id` with `document_ids` on `ChatRequest`**

Modify `src/models/schemas.py` — change the `ChatRequest` class:

```python
class ChatRequest(BaseModel):
    message: str
    top_k: int = 5
    document_ids: list[str] | None = None
```

- [ ] **Step 2: Attach sources to the chat response**

Replace the full contents of `src/routers/chat.py`:

```python
import json

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from src.models.schemas import ChatRequest
from src.services.embedder import embed_text
from src.services.generator import require_api_key, stream_answer
from src.database.vector_store import search_chunks

router = APIRouter(
    prefix="/chat",
    tags=["Chat"],
)

SYSTEM_PROMPT = (
    "You are a scientific paper summarizer. Answer the question using the "
    "provided context excerpts from the user's papers when they are relevant. "
    "Prefer concise bullet points."
)

# Excerpts in the X-Sources header are for display only, not re-parsed for
# grounding, so a short preview is enough.
SOURCE_EXCERPT_LENGTH = 200


@router.post("/")
async def chat(request: ChatRequest):
    # Fail before the stream starts so the client gets a real status code.
    try:
        require_api_key()
    except RuntimeError as err:
        raise HTTPException(status_code=503, detail=str(err)) from err

    # Retrieve: embed the question, pull the most similar ingested chunks —
    # scoped to the selected documents when the client passes document_ids.
    query_embedding = embed_text(request.message)
    results = search_chunks(
        query_embedding=query_embedding,
        top_k=request.top_k,
        document_ids=request.document_ids,
    )
    documents = results["documents"][0] if results["documents"] else []
    metadatas = results["metadatas"][0] if results["metadatas"] else []

    context = "\n\n".join(
        f"[excerpt {i + 1} — {meta.get('filename', 'unknown source')}] {text}"
        for i, (text, meta) in enumerate(zip(documents, metadatas))
    )
    user_prompt = (
        f"Context excerpts:\n{context}\n\nQuestion: {request.message}"
        if context
        else request.message
    )

    # Retrieval already ran, so sources are known before generation starts —
    # send them as a header rather than changing the streamed body format.
    sources = [
        {
            "filename": meta.get("filename", "unknown source"),
            "excerpt": text[:SOURCE_EXCERPT_LENGTH],
        }
        for text, meta in zip(documents, metadatas)
    ]

    async def answer_stream():
        try:
            async for delta in stream_answer(SYSTEM_PROMPT, user_prompt):
                yield delta
        except httpx.HTTPError as err:
            # Headers are already sent, so surface upstream failures in-band
            # instead of dropping the connection mid-answer.
            yield f"\n\n[generator error] {err}"
        except Exception as err:
            yield f"\n\n[generator error] {type(err).__name__}: {err}"

    return StreamingResponse(
        answer_stream(),
        media_type="text/plain; charset=utf-8",
        headers={"X-Sources": json.dumps(sources)},
    )
```

- [ ] **Step 3: Expose the header through CORS**

Modify `src/main.py` — update the `add_middleware` call:

```python
src.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:[0-9]+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Sources"],
)
```

- [ ] **Step 4: Verify manually**

This works without a real OpenRouter key or network access: `require_api_key()` only checks that the env var is non-empty, and if the actual OpenRouter call fails (bad key or no network), `answer_stream()` catches it and yields an inline error instead of crashing — the `X-Sources` header is already attached by then either way.

```bash
cd src
uv run python -c "
import sys
sys.path.insert(0, '..')

import json
import os
os.environ.setdefault('OPENROUTER_API_KEY', 'verification-placeholder')

from fastapi.testclient import TestClient
from src.main import src as app
from src.database import vector_store as vs
from src.services.embedder import embed_text

client = TestClient(app)

vs.add_chunk(
    chunk_id='verify-chat-1',
    text='Photosynthesis converts light into chemical energy.',
    embedding=embed_text('Photosynthesis converts light into chemical energy.'),
    document_id='verify-chat-doc',
    chunk_index=0,
    filename='bio.txt',
)

res = client.post('/chat/', json={'message': 'What is photosynthesis?', 'document_ids': ['verify-chat-doc']})
assert res.status_code == 200, res.text
sources = json.loads(res.headers['x-sources'])
assert len(sources) == 1, sources
assert sources[0]['filename'] == 'bio.txt', sources
assert 'Photosynthesis' in sources[0]['excerpt'], sources

vs.delete_chunks('verify-chat-doc')
print('chat sources OK')
"
```

Expected output: `chat sources OK`. Note: this proves the header is set server-side; whether the browser can actually *read* it cross-origin (the `expose_headers` change) is confirmed later in Task 9's browser check.

- [ ] **Step 5: Commit**

```bash
git add src/models/schemas.py src/routers/chat.py src/main.py
git commit -m "feat: scope chat retrieval to chosen documents and surface sources"
```

---

### Task 4: Document management endpoints

**Files:**
- Modify: `src/models/schemas.py` (add `DocumentMeta`, `DocumentsListResponse`)
- Modify: `src/routers/documents.py`

**Interfaces:**
- Consumes: `document_store.add_document/list_documents/get_document/delete_document` (Task 1), `vector_store.delete_chunks` (Task 2).
- Produces (used by Task 5, 9):
  - `POST /documents/` response: `{"document_id": str, "filename": str, "size_bytes": int, "chunks": int, "chunk_preview": [...]}`.
  - `GET /documents/` response: `{"documents": [{"id", "filename", "size_bytes", "status", "chunk_count", "error_message", "created_at"}, ...]}`, newest first.
  - `DELETE /documents/{document_id}` → `200 {"document_id": str, "deleted": true}` or `404`.

- [ ] **Step 1: Add document list schemas**

Modify `src/models/schemas.py` — append these classes at the end of the file:

```python
class DocumentMeta(BaseModel):
    id: str
    filename: str
    size_bytes: int
    status: str
    chunk_count: int
    error_message: str | None = None
    created_at: str

class DocumentsListResponse(BaseModel):
    documents: list[DocumentMeta]
```

- [ ] **Step 2: Rewrite the documents router**

Replace the full contents of `src/routers/documents.py`:

```python
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
    filename = file.filename or "document"
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
```

- [ ] **Step 3: Verify manually**

```bash
cd src
uv run python -c "
import sys
sys.path.insert(0, '..')

from fastapi.testclient import TestClient
from src.main import src as app
from src.database.vector_store import search_chunks
from src.services.embedder import embed_text

client = TestClient(app)

# Duplicate filenames must not collide.
upload = client.post('/documents/', files={'file': ('verify.txt', b'a small paper about photosynthesis', 'text/plain')})
assert upload.status_code == 200, upload.text
data = upload.json()
doc_id = data['document_id']
assert data['filename'] == 'verify.txt' and data['chunks'] >= 1 and data['size_bytes'] > 0, data

upload2 = client.post('/documents/', files={'file': ('verify.txt', b'a different paper about black holes', 'text/plain')})
doc_id_2 = upload2.json()['document_id']
assert doc_id_2 != doc_id

listing = client.get('/documents/')
assert listing.status_code == 200
docs = listing.json()['documents']
assert any(d['id'] == doc_id and d['status'] == 'ready' for d in docs), docs
assert any(d['id'] == doc_id_2 for d in docs), docs

results = search_chunks(query_embedding=embed_text('photosynthesis'), top_k=5, document_ids=[doc_id])
assert results['documents'][0], 'expected the first document to still have its own chunks'

# Corrupt upload: pypdf reliably raises on an empty PDF stream.
bad_upload = client.post('/documents/', files={'file': ('broken.pdf', b'', 'application/pdf')})
assert bad_upload.status_code == 422, bad_upload.text
bad_id = next(d['id'] for d in client.get('/documents/').json()['documents'] if d['filename'] == 'broken.pdf')
bad_doc = next(d for d in client.get('/documents/').json()['documents'] if d['id'] == bad_id)
assert bad_doc['status'] == 'error' and bad_doc['error_message'], bad_doc

# Delete cleanup + 404 on repeat.
delete = client.delete(f'/documents/{doc_id}')
assert delete.status_code == 200, delete.text
missing = client.delete(f'/documents/{doc_id}')
assert missing.status_code == 404

after_delete = client.get('/documents/').json()['documents']
assert all(d['id'] != doc_id for d in after_delete)

client.delete(f'/documents/{doc_id_2}')
client.delete(f'/documents/{bad_id}')
print('documents endpoint OK')
"
```

Expected output: `documents endpoint OK`.

- [ ] **Step 4: Commit**

```bash
git add src/models/schemas.py src/routers/documents.py
git commit -m "feat: persist a real document registry with listing and deletion"
```

---

### Task 5: Frontend types and API client

**Files:**
- Modify: `src/view/src/types.ts`
- Modify: `src/view/src/lib/api.ts`

**Interfaces:**
- Consumes: `GET /documents/`, `DELETE /documents/{id}`, `POST /chat/` `X-Sources` header, `POST /documents/` `size_bytes` field (Tasks 3, 4).
- Produces (used by Tasks 6, 7, 8):
  - `SourceExcerpt { filename: string; excerpt: string }`
  - `DocMeta.error?: string`
  - `Message.sources?: SourceExcerpt[]`
  - `listDocuments(): Promise<DocMeta[]>`
  - `deleteDocument(id: string): Promise<void>`
  - `streamChat(history: Message[], onChunk: (delta: string) => void, documentIds?: string[]): Promise<SourceExcerpt[]>`

- [ ] **Step 1: Update types**

Replace the full contents of `src/view/src/types.ts`:

```typescript
export type Role = 'user' | 'assistant'

export interface SourceExcerpt {
  filename: string
  excerpt: string
}

export interface Message {
  id: string
  role: Role
  content: string
  sources?: SourceExcerpt[]
}

export type DocStatus = 'uploading' | 'ready' | 'error'

export interface DocMeta {
  id: string
  name: string
  size: number
  status: DocStatus
  /** Number of chunks ingested into the vector store (backend response). */
  chunks?: number
  /** Set when status is 'error' — why the upload failed. */
  error?: string
}
```

- [ ] **Step 2: Update the API client**

Replace the full contents of `src/view/src/lib/api.ts`:

```typescript
import type { DocMeta, Message, SourceExcerpt } from '../types'

// In dev (Vite server on :5173) call the backend origin directly — override
// the port with VITE_API_URL if 8000 is taken; when the built frontend is
// served by FastAPI itself, stay same-origin (relative).
const API_BASE = import.meta.env.DEV
  ? (import.meta.env.VITE_API_URL ?? 'http://localhost:8000')
  : ''

const ACCEPTED_EXTENSIONS = ['.pdf', '.txt']

export function isAcceptedFile(name: string): boolean {
  const lower = name.toLowerCase()
  return ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext))
}

interface UploadResponse {
  document_id: string
  filename: string
  size_bytes: number
  chunks: number
}

// POST multipart/form-data to the backend; the server parses, chunks, embeds,
// and ingests the document before responding.
export async function uploadDocument(file: File): Promise<DocMeta> {
  const body = new FormData()
  body.append('file', file)

  const res = await fetch(`${API_BASE}/documents/`, { method: 'POST', body })
  if (!res.ok) throw new Error(await errorMessage(res))

  const data: UploadResponse = await res.json()
  return {
    id: data.document_id,
    name: data.filename,
    size: data.size_bytes,
    chunks: data.chunks,
    status: 'ready',
  }
}

interface DocumentListEntry {
  id: string
  filename: string
  size_bytes: number
  status: 'ready' | 'error'
  chunk_count: number
  error_message: string | null
  created_at: string
}

// GET the backend-authoritative document list — called on mount so a reload
// still shows previously uploaded papers.
export async function listDocuments(): Promise<DocMeta[]> {
  const res = await fetch(`${API_BASE}/documents/`)
  if (!res.ok) throw new Error(await errorMessage(res))

  const data: { documents: DocumentListEntry[] } = await res.json()
  return data.documents.map((doc) => ({
    id: doc.id,
    name: doc.filename,
    size: doc.size_bytes,
    status: doc.status,
    chunks: doc.chunk_count,
    error: doc.error_message ?? undefined,
  }))
}

export async function deleteDocument(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/documents/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await errorMessage(res))
}

// POST the latest user message; the backend streams the answer back as a
// chunked text response and attaches retrieved sources as a response header.
// When documentIds is non-empty, retrieval is scoped to just those papers.
export async function streamChat(
  history: Message[],
  onChunk: (delta: string) => void,
  documentIds: string[] = [],
): Promise<SourceExcerpt[]> {
  const message = [...history].reverse().find((m) => m.role === 'user')?.content
  if (!message) return []

  const res = await fetch(`${API_BASE}/chat/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, document_ids: documentIds }),
  })
  if (!res.ok) throw new Error(await errorMessage(res))
  if (!res.body) throw new Error('response has no body to stream')

  const sources = parseSources(res.headers.get('X-Sources'))

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    onChunk(decoder.decode(value, { stream: true }))
  }
  onChunk(decoder.decode()) // flush the decoder's tail

  return sources
}

function parseSources(header: string | null): SourceExcerpt[] {
  if (!header) return []
  try {
    const parsed = JSON.parse(header)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const data = await res.json()
    if (typeof data.detail === 'string') return data.detail
  } catch {
    // non-JSON error body — fall through
  }
  return `${res.status} ${res.statusText}`
}
```

- [ ] **Step 4: Verify manually**

```bash
cd src/view
npx tsc -b --noEmit
```

Expected output: no errors (empty output, exit code 0). This only type-checks — `UploadPanel.tsx`, `ChatPanel.tsx`, and `App.tsx` haven't been updated to the new prop shapes yet, so skip type-checking those specific files for now by confirming just `types.ts` and `lib/api.ts` compile in isolation:

```bash
cd src/view
npx tsc --noEmit --skipLibCheck src/types.ts src/lib/api.ts
```

Expected output: no errors.

- [ ] **Step 5: Commit**

```bash
git add src/view/src/types.ts src/view/src/lib/api.ts
git commit -m "feat: add document listing, deletion, and chat sources to the API client"
```

---

### Task 6: Multi-select document panel

**Files:**
- Modify: `src/view/src/components/UploadPanel.tsx`
- Modify: `src/view/src/App.css`

**Interfaces:**
- Consumes: `DocMeta` (Task 5).
- Produces (used by Task 8): `UploadPanel` props `{ docs: DocMeta[]; notice: string | null; activeDocIds: string[]; onFiles: (files: File[]) => void; onToggleDoc: (id: string) => void; onDelete: (id: string) => void }`.

- [ ] **Step 1: Rewrite `UploadPanel.tsx`**

Replace the full contents of `src/view/src/components/UploadPanel.tsx`:

```tsx
import { useRef, useState } from 'react'
import type { DocMeta } from '../types'

interface UploadPanelProps {
  docs: DocMeta[]
  notice: string | null
  activeDocIds: string[]
  onFiles: (files: File[]) => void
  onToggleDoc: (id: string) => void
  onDelete: (id: string) => void
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

const STATUS_LABEL: Record<DocMeta['status'], string> = {
  uploading: 'processing…',
  ready: 'ready',
  error: 'error',
}

export function UploadPanel({
  docs,
  notice,
  activeDocIds,
  onFiles,
  onToggleDoc,
  onDelete,
}: UploadPanelProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)

  return (
    <aside className="upload-panel">
      <h2 className="panel-title">Papers</h2>

      <div
        className={`dropzone${dragOver ? ' drag-over' : ''}`}
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click()
        }}
        onDragOver={(e) => {
          e.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragOver(false)
          onFiles(Array.from(e.dataTransfer.files))
        }}
      >
        <p>Drop PDF / text files here</p>
        <p className="dropzone-hint">or click to browse</p>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.txt"
        multiple
        hidden
        onChange={(e) => {
          if (e.target.files) onFiles(Array.from(e.target.files))
          e.target.value = '' // allow re-selecting the same file
        }}
      />

      {notice && <p className="rejection">{notice}</p>}

      {docs.length > 0 && (
        <p className="focus-hint">
          Check papers to scope the chat to them — leave all unchecked to search everything.
        </p>
      )}

      <ul className="doc-list">
        {docs.map((doc) => (
          <li key={doc.id} className={`doc-item${activeDocIds.includes(doc.id) ? ' active' : ''}`}>
            <div className="doc-row">
              <label className="doc-check">
                <input
                  type="checkbox"
                  checked={activeDocIds.includes(doc.id)}
                  disabled={doc.status !== 'ready'}
                  onChange={() => onToggleDoc(doc.id)}
                />
                <span className="doc-name" title={doc.name}>
                  {doc.name}
                </span>
              </label>
              <button
                type="button"
                className="doc-delete"
                aria-label={`Delete ${doc.name}`}
                onClick={() => {
                  if (window.confirm(`Delete "${doc.name}"? This removes it and its indexed content.`)) {
                    onDelete(doc.id)
                  }
                }}
              >
                ×
              </button>
            </div>
            <span className="doc-meta">
              {formatSize(doc.size)}
              {doc.chunks !== undefined && ` · ${doc.chunks} chunks`}
              <span className={`status-chip ${doc.status}`}>{STATUS_LABEL[doc.status]}</span>
            </span>
            {doc.error && <span className="doc-error">{doc.error}</span>}
          </li>
        ))}
      </ul>
    </aside>
  )
}
```

The previous whole-row `role="button"`/`onClick`/`onKeyDown` handling is dropped — the checkbox and delete button are each natively focusable and keyboard-operable, so the row itself no longer needs to fake button semantics.

- [ ] **Step 2: Add styles for the checkbox row, delete button, and error text**

Modify `src/view/src/App.css` — append after the existing `.status-chip.error { ... }` block (around line 125):

```css
.doc-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.doc-check {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
  cursor: pointer;
}

.doc-check .doc-name {
  flex: 1;
  min-width: 0;
}

.doc-delete {
  border: none;
  background: none;
  color: var(--muted);
  font-size: 1rem;
  line-height: 1;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
}

.doc-delete:hover {
  color: var(--danger);
  background: var(--danger-soft);
}

.doc-error {
  font-size: 0.75rem;
  color: var(--danger);
}
```

- [ ] **Step 3: Verify manually**

Full interactive verification (checkbox toggling, delete confirm, error display) happens in Task 9 once `App.tsx` wires real state through. For now, confirm the file compiles in isolation given its new prop shape:

```bash
cd src/view
npx tsc --noEmit --skipLibCheck src/components/UploadPanel.tsx
```

Expected output: no errors (any errors about `App.tsx` not yet passing the new props are expected and resolved in Task 8 — ignore errors reported in files other than `UploadPanel.tsx` itself).

- [ ] **Step 4: Commit**

```bash
git add src/view/src/components/UploadPanel.tsx src/view/src/App.css
git commit -m "feat: multi-select document checkboxes and delete action"
```

---

### Task 7: Sources display in chat

**Files:**
- Modify: `src/view/src/components/ChatPanel.tsx`
- Modify: `src/view/src/App.css`

**Interfaces:**
- Consumes: `Message.sources?: SourceExcerpt[]` (Task 5).
- Produces (used by Task 8): no prop shape change — `ChatPanelProps` stays `{ messages, isStreaming, focusLabel?, onSend }`; rendering just reads `msg.sources` when present.

- [ ] **Step 1: Render a sources block under each assistant message**

Modify `src/view/src/components/ChatPanel.tsx` — replace the message-rendering block inside the `.message-list` (the `messages.map(...)` call):

```tsx
        {messages.map((msg) => (
          <div key={msg.id} className={`message ${msg.role}`}>
            {msg.role === 'assistant' ? (
              <Markdown remarkPlugins={[remarkGfm, remarkBreaks]}>{msg.content}</Markdown>
            ) : (
              msg.content
            )}
            {msg.id === streamingId && <span className="stream-cursor" />}
            {msg.role === 'assistant' && msg.sources && msg.sources.length > 0 && (
              <div className="sources-block">
                <p className="sources-title">Sources</p>
                <ul className="sources-list">
                  {msg.sources.map((source, index) => (
                    <li key={index} className="source-item">
                      <span className="source-filename">{source.filename}</span>
                      <span className="source-excerpt">{source.excerpt}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ))}
```

The rest of the file (imports, `ChatPanelProps`, state, `submit`, the composer) is unchanged.

- [ ] **Step 2: Add styles for the sources block**

Modify `src/view/src/App.css` — append after the `.stream-cursor` / `@keyframes blink` block (around line 277):

```css
.sources-block {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
}

.sources-title {
  margin: 0 0 4px;
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--muted);
}

.sources-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.source-item {
  display: flex;
  flex-direction: column;
  font-size: 0.75rem;
}

.source-filename {
  font-weight: 600;
  color: var(--accent);
}

.source-excerpt {
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
```

- [ ] **Step 3: Verify manually**

```bash
cd src/view
npx tsc --noEmit --skipLibCheck src/components/ChatPanel.tsx
```

Expected output: no errors. Full visual/interactive verification happens in Task 9.

- [ ] **Step 4: Commit**

```bash
git add src/view/src/components/ChatPanel.tsx src/view/src/App.css
git commit -m "feat: display answer sources in the chat panel"
```

---

### Task 8: Wire multi-select state into App

**Files:**
- Modify: `src/view/src/App.tsx`

**Interfaces:**
- Consumes: `listDocuments`, `deleteDocument`, `streamChat` (Task 5); `UploadPanel` props (Task 6); `ChatPanel`/`Message.sources` (Task 7).
- Produces: the assembled, working `App` component — no further consumers within this plan.

- [ ] **Step 1: Rewrite `App.tsx`**

Replace the full contents of `src/view/src/App.tsx`:

```tsx
import { useEffect, useState } from 'react'
import './App.css'
import { ChatPanel } from './components/ChatPanel'
import { UploadPanel } from './components/UploadPanel'
import {
  deleteDocument,
  isAcceptedFile,
  listDocuments,
  streamChat,
  uploadDocument,
} from './lib/api'
import type { DocMeta, Message } from './types'

function App() {
  const [docs, setDocs] = useState<DocMeta[]>([])
  const [notice, setNotice] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [activeDocIds, setActiveDocIds] = useState<string[]>([])

  // Backend is the source of truth for the document list, so a reload still
  // shows previously uploaded papers.
  useEffect(() => {
    listDocuments()
      .then(setDocs)
      .catch((err) => setNotice(err instanceof Error ? err.message : String(err)))
  }, [])

  function toggleDoc(id: string) {
    setActiveDocIds((current) =>
      current.includes(id) ? current.filter((docId) => docId !== id) : [...current, id],
    )
  }

  async function handleDelete(id: string) {
    try {
      await deleteDocument(id)
      setDocs((prev) => prev.filter((d) => d.id !== id))
      setActiveDocIds((prev) => prev.filter((docId) => docId !== id))
    } catch (err) {
      setNotice(err instanceof Error ? err.message : String(err))
    }
  }

  async function handleFiles(files: File[]) {
    for (const file of files) {
      if (!isAcceptedFile(file.name)) {
        setNotice(`"${file.name}" skipped — only PDF and text files are supported`)
        continue
      }
      setNotice(null)

      // Optimistic entry; replaced once the upload resolves.
      const tempId = crypto.randomUUID()
      setDocs((prev) => [
        ...prev,
        { id: tempId, name: file.name, size: file.size, status: 'uploading' },
      ])
      try {
        const doc = await uploadDocument(file)
        setDocs((prev) => prev.map((d) => (d.id === tempId ? doc : d)))
        setActiveDocIds((prev) => [...prev, doc.id]) // new paper joins the current scope
      } catch (err) {
        // The backend may still have recorded a failed-upload row (with its
        // own real id) — drop the optimistic placeholder and refetch so it
        // shows up instead of silently vanishing.
        setDocs((prev) => prev.filter((d) => d.id !== tempId))
        setNotice(err instanceof Error ? err.message : String(err))
        try {
          setDocs(await listDocuments())
        } catch {
          // Keep whatever we had — the notice above already surfaced the failure.
        }
      }
    }
  }

  async function handleSend(text: string) {
    const userMsg: Message = { id: crypto.randomUUID(), role: 'user', content: text }
    const assistantId = crypto.randomUUID()
    const history = [...messages, userMsg]

    setMessages((prev) => [
      ...prev,
      userMsg,
      { id: assistantId, role: 'assistant', content: '' },
    ])
    setIsStreaming(true)
    try {
      const sources = await streamChat(
        history,
        (delta) => {
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantId ? { ...m, content: m.content + delta } : m)),
          )
        },
        activeDocIds,
      )
      setMessages((prev) =>
        prev.map((m) => (m.id === assistantId ? { ...m, sources } : m)),
      )
    } catch (err) {
      const note = err instanceof Error ? err.message : String(err)
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId ? { ...m, content: `${m.content}\n\n[error] ${note}` } : m,
        ),
      )
    } finally {
      setIsStreaming(false)
    }
  }

  const selectedNames = docs
    .filter((d) => activeDocIds.includes(d.id))
    .map((d) => d.name)

  return (
    <div className="app">
      <UploadPanel
        docs={docs}
        notice={notice}
        activeDocIds={activeDocIds}
        onFiles={handleFiles}
        onToggleDoc={toggleDoc}
        onDelete={handleDelete}
      />
      <ChatPanel
        messages={messages}
        isStreaming={isStreaming}
        focusLabel={selectedNames.length > 0 ? selectedNames.join(', ') : undefined}
        onSend={handleSend}
      />
    </div>
  )
}

export default App
```

- [ ] **Step 2: Verify the whole frontend type-checks and lints**

```bash
cd src/view
npx tsc -b
npm run lint
```

Expected output: both commands exit 0 with no errors.

- [ ] **Step 3: Commit**

```bash
git add src/view/src/App.tsx
git commit -m "feat: wire multi-select document scope through the app"
```

---

### Task 9: End-to-end manual verification

**Files:** none (verification only).

**Interfaces:** none — this task consumes the fully assembled app from Tasks 1–8.

- [ ] **Step 1: Start both servers**

```bash
cd src && uv run fastapi dev
```

In a second terminal:

```bash
cd src/view && npm run dev
```

Open the printed Vite URL (typically `http://localhost:5173`) in a browser.

- [ ] **Step 2: Walk the spec's manual test checklist**

Confirm each of these (from the design spec's Testing section):

1. **Duplicate filenames**: upload the same file twice. Both appear as separate entries in the Papers list — neither upload's content is lost or overwritten.
2. **Corrupt file**: upload an empty `.pdf` (e.g. `touch empty.pdf` then upload it). It appears in the list with an `error` status chip and a visible error message, and can still be deleted.
3. **Reload persistence**: reload the browser tab. Previously uploaded papers still appear in the Papers list (fetched from the backend, not reset).
4. **Multi-select scoping**: upload at least two real papers. With none checked, ask a question — the "Asking about" label reads "all papers". Check exactly one — the label shows its name and the answer's sources cite only that paper. Check both — the label lists both names.
5. **Deletion**: delete one of the papers. Confirm it disappears from the list, and a follow-up question scoped to "all papers" no longer surfaces content from the deleted paper.
6. **Sources accuracy**: ask a question with a specific paper selected and confirm the "Sources" block under the answer shows that paper's filename and an excerpt that plausibly relates to the answer.
7. **Cross-origin header check**: open the browser DevTools Network tab, inspect the `/chat/` response, and confirm an `X-Sources` response header is visible (proving `expose_headers` in Task 3 works in a real browser, not just in the `TestClient` check).

- [ ] **Step 3: Record the result**

No code changes are expected from this task. If any checklist item fails, fix the relevant task's code, re-run that task's verification step, then re-run this checklist from the top before considering the plan complete.
