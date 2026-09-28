from pydantic import BaseModel

class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    document_ids: list[str] | None = None

class SearchResult(BaseModel):
    text: str
    score: float

class SearchResponse(BaseModel):
    results: list[SearchResult]

class ChatRequest(BaseModel):
    message: str
    top_k: int = 5
    document_ids: list[str] | None = None

class ChatResponse(BaseModel):
    answer: str
    sources: list[SearchResult]

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