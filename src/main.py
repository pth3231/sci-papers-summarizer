from pathlib import Path

from dotenv import load_dotenv

# Load .env before anything that reads environment variables at import time
# (src.services.generator reads OPENROUTER_BASE_URL on import). Real
# environment variables keep precedence over .env values.
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.routers.documents import router as documents_router
from src.routers.search import router as search_router
from src.routers.chat import router as chat_router


src = FastAPI(
    title="LNG302 RAG Backend",
    description="Backend API for the LNG302 NLP project",
    version="0.1.0",
)

# The Vite dev server serves the frontend on a different origin (and may
# bump its port when 5173 is taken), so allow any local development port.
src.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:[0-9]+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)


src.include_router(documents_router)
src.include_router(search_router)
src.include_router(chat_router)


@src.get("/health")
def health_check():
    return {"status": "ok"}


# Serve the built frontend from the same origin as the API. Mount last so the
# API routes registered above take precedence; `html=True` makes "/" return
# index.html. Skipped when the frontend hasn't been built (API-only mode).
FRONTEND_DIST = Path(__file__).resolve().parents[1] / "src" / "view" / "dist"
if FRONTEND_DIST.is_dir():
    src.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")