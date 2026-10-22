# GLM-vision parser + project cleanup

Date: 2026-10-22

## Why

Three standing constraints for this project:

1. OCR/text parsing should go through tool-calling to the GLM model configured in `.env` (`LLM_MODEL=glm-5.2`), not a local model.
2. No local image-processing models, local LLMs, or other RAM-heavy model processes.
3. Remove dead code and apply low-risk optimizations found during a project-wide audit.

Audit found one violation of (1)/(2): `src/services/parser.py` uses `marker-pdf`, which loads a local layout/OCR model stack (surya) and, per `.env`, spawns a local `llama.cpp` server for inference. This is the only local-model component in the project aside from the embedder, which stays (small, deterministic, out of scope — confirmed with user).

## Scope

### 1. Dead code removal
- `src/services/chunker.py`: delete `chunk_text()` — zero callers anywhere (grepped source + tests).
- `.env`: remove `SURYA_INFERENCE_BACKEND`, `LLAMA_CPP_BINARY`, and the commented-out OpenRouter block — none read by any code path once marker is removed.
- `pyproject.toml`: drop the `marker-pdf` dependency.

### 2. Replace marker with GLM 5.2 vision calls

Current (`src/services/parser.py`):
- `marker_convert()` lazily builds a `PdfConverter(artifact_dict=create_model_dict())` (marker + surya local models), converts the whole PDF in one call, returns `(markdown, {image_name: PIL.Image})`.
- `parse_pdf_file()` saves those images to `figures_dir` and returns a `ParsedDocument`.

New design:
- Add dependency `pymupdf` (the `fitz` module) for deterministic PDF→image page rendering — a C-library renderer, not an ML model.
- New function `render_pages(pdf_path: str) -> list[PIL.Image]`: opens the PDF with `fitz.open()`, rasterizes each page to a `PIL.Image` (via `page.get_pixmap()` → `Image.frombytes`).
- New function `vision_parse_page(image: PIL.Image) -> PageResult` (module-level seam, mirrors today's `marker_convert` seam so tests can monkeypatch it):
  - Encodes the page image as base64 PNG.
  - Calls GLM 5.2 through the Z.ai chat completions endpoint (same `httpx`, same `LLM_API_KEY`/`LLM_BASE_URL`/`LLM_MODEL` env vars as `generator.py`) with an image content block and a prompt instructing the model to return:
    - `markdown`: the page's content as markdown, preserving heading levels.
    - `figures`: a JSON list of `{bbox: [x0, y0, x1, y1], caption: str}` for any figures/tables on the page, in the page image's pixel coordinates.
  - Parses the JSON response into a `PageResult(markdown: str, figures: list[FigureRegion])` dataclass.
- `parse_pdf_file()` rewritten to:
  1. `render_pages(file_path)` to get page images.
  2. Call `vision_parse_page()` per page.
  3. For each `FigureRegion`, crop the region out of that page's image with `Image.crop(bbox)` (Pillow — image manipulation, not a model) and save it under `figures_dir`, building a `Figure(name=..., caption=...)`.
  4. Concatenate page markdown (in page order) into one document-level markdown string.
  5. Return `ParsedDocument(markdown=..., figures=...)` — same shape as today, so `chunker.py` and `routers/documents.py` need no changes.
- `marker_convert` is deleted along with the `marker` imports. `parse_text_file` and the `.pdf` vs other-extension dispatch in `parse_file` are unchanged.
- Error handling: if GLM returns malformed JSON for a page, raise (caught by the existing `except Exception` in `routers/documents.py:62`, which already records the upload as `status="error"` with the message) — no new error-handling path needed.

Test impact (`src/tests/test_parser.py`): tests that monkeypatch `parser.marker_convert` move to monkeypatching `parser.vision_parse_page` (and `render_pages` where a fake page image is needed), returning canned `PageResult`/image data instead of `(markdown, images)` tuples.

### 3. Embedder
No change. `src/services/embedder.py` keeps `sentence-transformers/all-MiniLM-L6-v2` loaded locally.

### 4. Optimization
- `src/services/generator.py`: replace the per-call `httpx.AsyncClient(timeout=None)` (created fresh in `stream_answer` on every request) with a single module-level pooled client, closed on app shutdown.
- New `vision_parse_page` in `parser.py` reuses that same pooled client rather than opening its own.

## Out of scope
- Z.ai embeddings API migration (user chose to keep the local embedder).
- Any UI/frontend changes.
- Changing the `/documents` upload API contract — request/response shapes are unchanged.

## Testing
- Update `src/tests/test_parser.py` to mock the new GLM vision seam instead of marker.
- `src/tests/test_chunker.py`: remove any reference to `chunk_text` if present (none found in current grep, but re-check at implementation time).
- `src/tests/test_documents_figures.py`: should keep passing unchanged since `ParsedDocument` shape is preserved — verify as part of implementation.
- Full suite (`pytest -q`) must pass before considering this done.
