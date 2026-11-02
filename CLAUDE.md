# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

A RAG-based tool that summarizes scientific papers into cited bullet points, built
for intensive thesis-related reading. See `PRODUCT.md` (what/why), `DESIGN.md` (the UI
world + tokens), and `CONVENTIONS.md` (workflow + guardrails) for the fuller picture;
this file is the architecture map.

## Project

The pipeline (see README.md and assets/image.png):

1. **Ingest**: upload a document to the FastAPI server → parse (PDFs are text-first via
   pymupdf, escalating to a GLM vision call per page only when a page looks untrustworthy;
   embedded images get per-image vision captions — see `src/services/parser.py`) → chunk
   sections + figures (`chunker.py`) → embed (`embedder.py`) → store in the `documents_v2`
   Chroma collection plus a SQLite document registry. Upload and lazy re-parse share one
   pipeline (`src/services/ingest.py`).
2. **Retrieve & Generate**: when the user has selected specific papers, the *whole text*
   of those papers is sent (all text/reference chunks in order, figures appended) so a
   summary isn't starved by a similarity slice; with no selection, fall back to an
   embedded-question similarity search across the whole corpus (`src/routers/chat.py`,
   `vector_store.get_document_chunks` / `search_chunks`) →
   combine chunks with the prompt → LLM (Z.ai GLM via its OpenAI-compatible API;
   default `glm-4.6`, configured by `LLM_MODEL` / `LLM_BASE_URL` / `LLM_API_KEY` in the
   root `.env`) → stream a bullet-point answer back to the UI, each bullet ending in a
   `[n]` citation chip that resolves to the cited section or figure.

Documents whose stored chunks predate the running `PARSER_VERSION` are lazily re-parsed
from their original upload on next use, so pipeline upgrades don't require manual
re-upload. Vision calls degrade gracefully — a failed per-page or per-image call falls
back to extracted text (or drops just that caption), never the whole document.

## Commands

Backend (uv-managed, run from the **repo root** — `uploads/`, `chroma_db`, and
`document_registry.db` resolve relative to CWD, so running from `src/` creates a separate
store):

- `uv run fastapi dev` — dev server with reload
- `uv run pytest src/tests -q` — backend test suite
- `.venv/bin/python -m uvicorn src.main:src --port 8000` — production-style run

Frontend (from `src/view/`, npm):

- `npm run dev` — Vite dev server with HMR
- `npm run build` — type-checks (`tsc -b`) then builds; type errors fail the build
- `npm run lint` — ESLint over the whole frontend
- `npm run preview` — serve the production build

## Structure

Backend (FastAPI, layered — thin routers, logic in services, persistence in database):

- `src/main.py` — app factory (`src`), CORS, router wiring, serves `src/view/dist` when built.
- `src/routers/` — thin HTTP layer: `documents.py` (upload/list/delete/figures),
  `chat.py` (streamed cited answers), `search.py`.
- `src/services/` — business logic: `parser.py`, `chunker.py`, `embedder.py`,
  `generator.py` (GLM client), `ingest.py` (shared parse+chunk+embed + lazy re-parse).
- `src/database/` — persistence: `vector_store.py` (Chroma `documents_v2`),
  `document_store.py` (SQLite registry).
- `src/models/schemas.py` — Pydantic request/response models.
- `src/tests/` — pytest suite (parser, chunker, ingest, chat citations/top-k, vector
  store, generator, figures, smoke).

Frontend:

- `src/view/` — React 19 + TypeScript (Vite, ESLint flat config in eslint.config.js).
  Entry `src/view/src/main.tsx` → `App.tsx`, composing `UploadPanel` + `ChatPanel`;
  design tokens in `index.css`, inline SVG icons in `components/Icons.tsx`.
