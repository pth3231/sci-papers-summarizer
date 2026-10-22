import json
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from src.database import document_store
from src.models.schemas import ChatRequest
from src.routers.documents import UPLOAD_DIR
from src.services.chunker import IMAGE_LINE_RE
from src.services.embedder import embed_text
from src.services.generator import require_api_key, stream_answer
from src.services.ingest import ensure_fresh
from src.database.vector_store import search_chunks

router = APIRouter(
    prefix="/chat",
    tags=["Chat"],
)

SYSTEM_PROMPT = (
    "You are a scientific paper summarizer. Answer the question using the "
    "provided context excerpts from the user's papers when they are relevant. "
    "Prefer concise bullet points. End each bullet or claim with its citation "
    "marker(s), like [1] or [2][5]. Cite only the numbered excerpts provided, "
    "and say so explicitly when the context is insufficient."
)

# Excerpts in the X-Sources header are for display only, not re-parsed for
# grounding, so a short preview is enough.
SOURCE_EXCERPT_LENGTH = 200

# In-band marker for the frontend (ERROR_SENTINEL in src/view/src/lib/api.ts):
# when generation fails after the stream has started, the response continues
# with this sentinel so the client can render an error banner instead of
# mistaking the failure report for answer text.
GENERATOR_ERROR_SENTINEL = "---generator-error---"


def build_context(documents: list[str], metadatas: list[dict]) -> str:
    return "\n\n".join(
        f"[{i + 1}] ({meta.get('filename', 'unknown source')} — "
        f"{meta.get('section') or 'no section'}) {text}"
        for i, (text, meta) in enumerate(zip(documents, metadatas))
    )


def _clean_excerpt(text: str) -> str:
    """Strip raw markdown image syntax (`![name](path)`) a chunk's text may
    carry for a figure — the image is already shown separately via
    figure_url, so the excerpt should read as plain caption/body text."""
    lines = [line for line in text.splitlines() if not IMAGE_LINE_RE.match(line.strip())]
    return "\n".join(lines).strip()


def build_sources(documents: list[str], metadatas: list[dict]) -> list[dict]:
    sources = []
    for i, (text, meta) in enumerate(zip(documents, metadatas)):
        figure_url = None
        if meta.get("figure_path"):
            figure_url = (
                f"/documents/{meta.get('document_id')}/figures/"
                f"{Path(meta['figure_path']).name}"
            )
        sources.append(
            {
                "index": i + 1,
                "filename": meta.get("filename", "unknown source"),
                "section": meta.get("section", ""),
                "kind": meta.get("kind", "text"),
                "figure_url": figure_url,
                "excerpt": _clean_excerpt(text)[:SOURCE_EXCERPT_LENGTH],
            }
        )
    return sources


@router.post("/")
async def chat(request: ChatRequest):
    # Fail before the stream starts so the client gets a real status code.
    try:
        require_api_key()
    except RuntimeError as err:
        raise HTTPException(status_code=503, detail=str(err)) from err

    # Lazily re-parse any in-scope document whose stored chunks predate the
    # current parser — right before it's used for retrieval, not on upload
    # or on toggle, so this cost is only paid when the document is actually
    # about to answer a question.
    target_ids = request.document_ids or [
        doc["id"] for doc in document_store.list_documents() if doc["status"] == "ready"
    ]
    for document_id in target_ids:
        await run_in_threadpool(ensure_fresh, document_id, UPLOAD_DIR)

    # Retrieve: embed the question, pull the most similar ingested chunks —
    # scoped to the selected documents when the client passes document_ids.
    # top_k <= 0 (e.g. no documents uploaded yet) means "don't retrieve at
    # all" — Chroma's n_results must be >= 1, so skip the call entirely.
    if request.top_k > 0:
        query_embedding = embed_text(request.message)
        results = search_chunks(
            query_embedding=query_embedding,
            top_k=request.top_k,
            document_ids=request.document_ids,
        )
        documents = results["documents"][0] if results["documents"] else []
        metadatas = results["metadatas"][0] if results["metadatas"] else []
    else:
        documents, metadatas = [], []

    context = build_context(documents, metadatas)
    user_prompt = (
        f"Context excerpts:\n{context}\n\nQuestion: {request.message}"
        if context
        else request.message
    )

    # Retrieval already ran, so sources are known before generation starts —
    # send them as a header rather than changing the streamed body format.
    sources = build_sources(documents, metadatas)

    async def answer_stream():
        try:
            async for delta in stream_answer(SYSTEM_PROMPT, user_prompt):
                yield delta
        except httpx.HTTPError as err:
            # Headers are already sent, so report upstream failures in-band —
            # flagged with the sentinel — instead of dropping the connection
            # mid-answer.
            yield f"\n{GENERATOR_ERROR_SENTINEL}\n{err}"
        except Exception as err:
            yield f"\n{GENERATOR_ERROR_SENTINEL}\n{type(err).__name__}: {err}"

    return StreamingResponse(
        answer_stream(),
        media_type="text/plain; charset=utf-8",
        headers={"X-Sources": json.dumps(sources)},
    )
