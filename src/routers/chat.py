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
