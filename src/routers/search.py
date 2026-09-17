from fastapi import APIRouter

from src.models.schemas import SearchRequest, SearchResponse, SearchResult
from src.services.embedder import embed_text
from src.database.vector_store import search_chunks

router = APIRouter(prefix="/search", tags=["Search"])

@router.post("/", response_model=SearchResponse)
def search(request: SearchRequest):
    query_embedding = embed_text(request.query)

    results = search_chunks(query_embedding=query_embedding, top_k=request.top_k)

    search_results = []

    documents = results["documents"][0]
    distances = results["distances"][0]

    for text, distance in zip(documents, distances):
        search_results.append(SearchResult(text=text, score=distance))

    return SearchResponse(results=search_results)