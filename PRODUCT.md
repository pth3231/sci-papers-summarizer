# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary users are the two thesis authors (Phan Thai Hoa and Davian) themselves — not a broader student or researcher audience. The job: during intensive thesis-related literature review, upload a scientific paper and ask questions to get bullet-point answers instead of re-reading the full PDF each time.

## Product Purpose

Reduce the time and error cost of reading research papers during thesis work. The tool ingests a PDF (parsed, chunked, embedded into a vector store), then answers natural-language questions about it with bullet-point summaries, streamed back from an LLM (Z.ai GLM).

## Positioning

Citation traceability is the core differentiator from pasting a PDF into a generic chatbot: every bullet point ends in a citation chip ([n]) that resolves to a specific section or figure. The Sources panel shows which sources were actually cited vs. not, figure sources render the source image inline, and math renders via KaTeX — so answers are verifiable against the original document, not just plausible-sounding.

## Operating Context

Workflow: upload a PDF → FastAPI backend parses it (text-first via pymupdf, escalating to GLM vision per-page only when a page looks untrustworthy; embedded images get per-image vision captions) → chunk sections and figures → embed → store in the `documents_v2` Chroma collection → user asks a question → embed the question → similarity search → relevant chunks + prompt go to the LLM → streamed, cited answer in the chat UI.

Documents uploaded before the marker/vision-parser switch are stale and must be re-uploaded; a `PARSER_VERSION` bump also triggers lazy re-parse from the original upload on next use, so pipeline upgrades don't require manual delete + re-upload.

## Capabilities and Constraints

- Single-user, local/trusted-use tool — no accounts, login, or multi-user access control is in scope now or planned.
- Backend: FastAPI, business logic in `src/services/`, thin routers in `src/routers/`, persistence in `src/database/` (Chroma + a document registry SQLite DB), Pydantic schemas in `src/models/schemas.py`.
- Frontend: React 19 + TypeScript + Vite. Two main panels today — `UploadPanel` and `ChatPanel` — composed in `App.tsx`.
- LLM is Z.ai's GLM (OpenAI-compatible API), configured via `.env` (`LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL`); no local model download required, but a network connection to the LLM endpoint is required for every upload (parsing) and question (answering).
- Both upload and lazy re-parse must share the same ingest pipeline (`src/services/ingest.py`) — no duplicated parse/chunk/embed logic in routers.
- Vision calls (parsing) must degrade gracefully: a failed per-page or per-image vision call falls back to extracted text or drops just that caption, never discards the rest of the document.

## Evidence on Hand

No real test papers, user testimonials, or usage data are recorded here. Treat any sample PDFs used during development as scratch content, not product evidence to reference in marketing-style copy (not applicable yet since this is an internal tool, not a marketing surface).

## Product Principles

1. Trust the answer by tracing it — every claim should be checkable against the exact section or figure it came from, not just asserted.
2. Never regress the pipeline's resilience — vision/parsing failures degrade a single page or image, not the whole document.
3. This is a working tool for two people doing real thesis research, not a product being prepared for strangers — prioritize function and correctness for that known workflow over generalized UX polish for unknown users.
4. Pipeline upgrades (parser version bumps, etc.) must stay backward-compatible via lazy re-parse, not force manual re-uploads.
