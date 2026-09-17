from pydantic import BaseModel

class SearchRequest(BaseModel):
    query: str
    top_k: int = 5

class SearchResult(BaseModel):
    text: str
    score: float

class SearchResponse(BaseModel):
    results: list[SearchResult]

class ChatRequest(BaseModel):
    message: str
    top_k: int = 5

class ChatResponse(BaseModel):
    answer: str
    sources: list[SearchResult]