# Design: Marker-Based Ingestion + Validated Citations

Date: 2026-10-05
Status: approved (pending spec review)

## Problem

The current pipeline discards everything that makes scientific papers citable and
readable:

- `parser.py` joins pypdf page texts into one string — page numbers, headings,
  tables, equations, and figures are all lost. Tables garble; equations become
  noise; scanned pages silently yield empty text.
- `chunker.py` cuts fixed 1000-char windows with 200-char overlap — mid-word,
  mid-sentence — and 1000 chars already exceeds what the embedding model
  (MiniLM-L6-v2, ~256-token truncation) can encode.
- Chunks carry only `document_id`, `chunk_index`, `filename` — there is nothing
  to cite with (no section, page, or figure identity).
- The model is never instructed to cite; the UI shows a flat filename list and
  cannot distinguish answer text from failure reports (fixed separately:
  sentinel error channel).

## Requirements (from user decisions)

1. PDFs are born-digital (arXiv/publisher); OCR not required.
2. Tables and equations must survive ingestion readably.
3. Figures are extracted; captions indexed; cited figures displayed in the UI.
4. Citations are inline `[n]` markers tied to a numbered sources list, with
   validation: markers not matching a retrieved source are flagged, uncited
   sources are visibly dimmed.
5. Hardware: RTX 3050 Laptop 4GB, 35GB disk free — marker fits.

## Non-goals

- Embedding-model upgrade (MiniLM stays; a future `bge-small` swap is one
  re-embed away once this lands).
- Async/background uploads (marker on GPU is seconds-per-paper; synchronous is
  acceptable).
- Page-number citations via PDF post-mapping — sections are the citation anchor;
  page numbers can be layered on later if missed.
- Multi-turn conversational memory.

## Architecture

Pipeline shape unchanged. Changes are swaps at existing seams:

| Seam | Change |
|---|---|
| `src/services/parser.py` | marker-pdf; returns `ParsedDocument(markdown, figures)` |
| `src/services/chunker.py` | markdown-structure-aware chunker (sections, paragraphs, figures) |
| `src/database/vector_store.py` | new metadata fields; collection `documents_v2` |
| `src/routers/documents.py` | figure storage + `GET /documents/{id}/figures/{name}` |
| `src/routers/chat.py` | numbered context excerpts + citation instruction + richer `X-Sources` |
| frontend (`api.ts`, `ChatPanel.tsx`, `App.css`) | `[n]` chips, source states, figure display |

## Phase 1 — Ingestion foundation

### Parser

- Add `marker-pdf` dependency (pulls torch/surya; ~2–4GB model download on
  first run, cached). Use the programmatic converter API (not the CLI).
- `parse_file(path, figures_dir) -> ParsedDocument` where
  `ParsedDocument = { markdown: str, figures: [{ name, caption?, section? }] }`.
  PDF: marker with image extraction into `figures_dir` (the router passes
  `uploads/<doc_id>/figures/`). `.txt`: markdown = raw text, no figures.
- Exact marker config flags (image extraction, output format) verified during
  implementation planning; pin the dependency version.

### Chunker v2

- Walk markdown headings to maintain a section path (e.g. "3 Methods > 3.2
  Training"). Heading text is content, not a chunk by itself.
- Within a section, pack whole paragraphs into chunks targeting **600–900
  chars** (fits MiniLM's truncation window; no mid-sentence cuts). If a single
  paragraph exceeds the budget, split it on sentence boundaries. Overlap: the
  final sentence of the previous chunk prefixes the next (sentence-level, not
  character-level).
- Figure chunks: caption text (plus section context) becomes a
  `kind: "figure"` chunk so "what does Figure 3 show" retrieves it.
- Chunk record: `chunk_id, document_id, text, chunk_index, section, kind,
  figure_path?`.

### Storage & serving

- `vector_store.py`: `get_or_create_collection("documents_v2")`; `add_chunk`
  writes the extended metadata. Old `documents` collection is orphaned (not
  migrated).
- `documents.py`: figures land under `uploads/<doc_id>/figures/`; new endpoint
  `GET /documents/{document_id}/figures/{name}` serves them via `FileResponse`
  with a sanitized name (no path traversal — same hardening as upload
  filenames). Registry schema unchanged; `chunk_count` includes figure chunks.
- Failures (marker error, empty text) flow through the existing 422 +
  error-row path so failed uploads stay visible and deletable.

### Migration

Re-upload papers after upgrade. Old documents' chunks live only in the orphaned
collection — retrieval returns nothing for them, so delete old rows via the UI.

## Phase 2 — Citations

### Backend (`chat.py`)

- Context format: `[1] (filename — section) text` … `[k] …`.
- System prompt addition: "End each bullet or claim with its citation
  marker(s), e.g. `[1]` or `[2][5]`. Cite only the provided excerpts. If the
  context is insufficient, say so explicitly."
- `X-Sources` entries: `{ index, filename, section, kind, figure_url?, excerpt }`
  where `figure_url` is the serving endpoint path for figure chunks.

### Frontend

- After the stream completes, extract `[n]` markers from the final message
  (regex adequate given the instruction; markdown-link collisions excluded by
  requiring the no-`(` lookahead).
- Render valid markers as small chips visually tied to the numbered sources
  list. Markers outside `1..k` render with an invalid/warning style
  (hallucinated citation). Sources list shows cited entries normally and
  uncited entries dimmed.
- Figure sources render the actual image (caption + `<img>`) in the Sources
  block.

## Testing & verification

- Introduce `pytest` (backend): chunker unit tests over sample markdown
  (section paths, packing budget, sentence splits, figure chunks), parser
  contract test on a tiny fixture PDF (markdown non-empty, figure file
  created), citation-context formatting tests.
- Keep the Node sentinel-stream test pattern for stream logic.
- Manual E2E: upload a real paper → inspect chunk preview (sections, figure
  chunks) → ask questions → verify chips, validation styling, and figure
  display in the browser.

## Risks

- Marker API drift between versions — pin version, verify flags at planning.
- 4GB VRAM edge: marker's default models fit but monitor; fallback to CPU
  automatically.
- `X-Sources` header size with figure URLs — bounded by `top_k` (default 5).
- Re-ingestion cost on any future embedder change — accepted, documented.
