# CONVENTIONS.md

Working conventions for this repo (a RAG-based scientific-paper summarizer: FastAPI
backend + React 19/Vite frontend). These codify the development workflow, guardrails,
and best practices. They complement `CLAUDE.md` (project architecture) — read that
first for how the pipeline fits together.

## Development workflow

Move linearly through the phases. One core tool per phase; supporting tools alongside.

### 1. Plan (before touching code)

- Start with **brainstorming** to pin down intent, requirements, and design.
- For non-trivial features, follow with **feature-dev** to produce a concrete blueprint:
  files to create/modify, component design, data flow, and build order.
- Route security-sensitive surfaces through a **security review before writing code** —
  upload handling, the chat/retrieval endpoints, and API-key/`.env` config are the
  highest-risk areas here (injection, broken authorization, OWASP Top 10).
- Effort: architecture/audits at the highest effort; drop down for routine builds.

### 2. Backend first (TDD)

- Write the test, watch it fail (RED), then make it pass (GREEN). Extend the existing
  suite in `src/tests/` (parser, chunker, ingest, chat citations/top-k, vector store,
  smoke test) rather than starting a parallel one.
- Run quietly: `uv run pytest src/tests -q`. Read failures from the tail, not streamed logs.
- Keep the layering: business logic in `src/services/`, routing thin in `src/routers/`,
  persistence in `src/database/`, Pydantic models in `src/models/schemas.py`.

### 3. Frontend (design, don't boilerplate)

- Never ship default boilerplate CSS/layout for user-facing UI. Enforce curated design
  principles and make fine-grained adjustments via live iteration instead of regenerating
  whole components in the terminal.
- Build gate: `npm run build` (type-checks via `tsc -b` — type errors fail the build) and
  `npm run lint` must both pass before the work is considered done.

### 4. Wire + verify end-to-end

- Run both halves: backend `uv run fastapi dev`, frontend `npm run dev` (Vite HMR).
- Drive the **real flow** — upload → parse → ask → streamed answer with citations and
  sources — and observe behavior. Inspect failed fetches and console errors live.
- No speculative fixes: trace the actual console/network/DOM state before editing.
- Add E2E browser assertions for web flows; validate changes against them before marking
  a task complete.

### 5. Cleanup before merge

- Run the code simplifier on the changed files: flatten nested conditionals, remove dead
  code and unnecessary abstractions. Behavioral logic and existing tests stay intact.
- Follow with a correctness-focused code review, then a security review of the branch diff.

## Git guardrails

- **Prohibited by default:** `git push`, `git merge`, and creating/approving PRs targeting
  `main` / `origin/main`.
- **Exception:** perform a restricted action only on explicit, task-specific instruction.
  Before doing so, output a **bold warning** naming the exact action and target branch,
  then confirm authorization.
- Commit or push only when asked. If on the default branch, branch first.

## Context & token hygiene

- Never read a 300+ line file whole — inspect specific sections via line ranges, `grep`,
  or symbol lookups.
- Run tests/builds/linters with quiet flags (`pytest -q`, `git diff --stat`); read
  failures from filtered output, not full logs.
- After edits, give a one-sentence summary — don't re-print the modified code in chat.

## Project-specific best practices

- **Consistent working directory.** `uploads/`, `chroma_db`, and `document_registry.db`
  are all resolved relative to the process's CWD. Always run the server (and tests) from
  the **repo root** — running from `src/` produces a separate, non-interchangeable store.
- **Parser is text-first.** PDFs use pymupdf direct text extraction per page; a page only
  escalates to a full-page vision call when it looks untrustworthy (near-empty or high
  math-symbol density). Embedded images on an otherwise-fine page are captioned via a
  cheaper per-image vision call. Don't reintroduce whole-page vision as the default.
- **Vision calls degrade gracefully.** Per-page and per-image vision calls are independent;
  a single failed call (timeout, rate limit, transient 5xx) must fall back to extracted
  direct text (or drop just that one caption) — never discard the rest of the document.
- **Respect `PARSER_VERSION`.** Chunks/documents carry a parser version; documents whose
  stored chunks predate the running parser are lazily re-parsed from their original upload
  on next use (`src/services/ingest.py`). A pipeline upgrade must not require manual
  delete + re-upload — preserve this behavior when touching the parse/ingest path.
- **Shared ingest pipeline.** Both upload and lazy re-parse go through `src/services/ingest.py`.
  Keep parse+chunk+embed logic there rather than duplicating it in routers.

## Commands reference

Backend (uv-managed, from repo root):

- `uv run fastapi dev` — dev server with reload
- `.venv/bin/python -m uvicorn src.main:src --port 8000` — production-style run
- `uv run pytest src/tests -q` — backend test suite

Frontend (from `src/view/`, npm):

- `npm run dev` — Vite dev server with HMR
- `npm run build` — type-checks then builds
- `npm run lint` — ESLint over the frontend
- `npm run preview` — serve the production build
