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


@router.post("/")
async def chat(request: ChatRequest):
    # Fail before the stream starts so the client gets a real status code.
    try:
        require_api_key()
    except RuntimeError as err:
        raise HTTPException(status_code=503, detail=str(err)) from err

    # Retrieve: embed the question, pull the most similar ingested chunks.
    query_embedding = embed_text(request.message)
    results = search_chunks(query_embedding=query_embedding, top_k=request.top_k)
    documents = results["documents"][0] if results["documents"] else []

    context = "\n\n".join(
        f"[excerpt {i + 1}] {text}" for i, text in enumerate(documents)
    )
    user_prompt = (
        f"Context excerpts:\n{context}\n\nQuestion: {request.message}"
        if context
        else request.message
    )

    async def answer_stream():
        try:
            async for delta in stream_answer(SYSTEM_PROMPT, user_prompt):
                yield delta
        except httpx.HTTPError as err:
            # Headers are already sent, so surface upstream failures in-band
            # instead of dropping the connection mid-answer.
            yield f"\n\n[generator error] {err}"

    return StreamingResponse(
        answer_stream(), media_type="text/plain; charset=utf-8"
    )
