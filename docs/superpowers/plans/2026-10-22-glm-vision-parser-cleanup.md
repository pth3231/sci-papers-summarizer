# GLM-Vision Parser + Project Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the local marker/surya OCR model stack and other dead project artifacts, replacing PDF parsing with GLM 5.2 vision tool-calls, while keeping the local embedder and the existing upload API contract unchanged.

**Architecture:** `src/services/parser.py` renders PDF pages to images with PyMuPDF (deterministic, no ML model), sends each page image to GLM 5.2 via the Z.ai chat-completions endpoint for structured markdown + figure-region extraction, then crops figures locally with Pillow. `src/services/generator.py` gets a pooled `httpx.AsyncClient` instead of opening one per chat request. A duplicate, stale `src/pyproject.toml`/`src/.venv`/`src/uv.lock`/`src/README.md` project scaffold and one dead function are deleted.

**Tech Stack:** FastAPI, httpx, PyMuPDF (`fitz`), Pillow, pytest (no new test plugins).

## Global Constraints

- No local image-processing models, local LLMs, or other RAM-heavy local model processes may remain in the project (confirmed violation: `marker-pdf`'s surya/llama.cpp stack — being removed).
- OCR/PDF text parsing must go through tool-calling to the GLM model configured via `LLM_MODEL`/`LLM_BASE_URL`/`LLM_API_KEY` in `.env` (currently `glm-5.2`), not a local model.
- The local embedder (`sentence-transformers/all-MiniLM-L6-v2` in `src/services/embedder.py`) is explicitly out of scope — do not touch it.
- `ParsedDocument`/`Figure` shapes, and the `/documents/` upload API contract, must not change — `chunker.py` and `routers/documents.py` need no changes.
- The root `pyproject.toml` + root `.venv` is the real, in-use project environment (confirmed by user). `src/pyproject.toml`, `src/uv.lock`, `src/.venv`, `src/README.md` are a stale duplicate scaffold and must be deleted, with their pytest marker config (`-m 'not marker'`) re-created in the root `pyproject.toml`.
- User asked for lower effort wherever reasonable: no new test-framework plugins (e.g. pytest-asyncio) — async code is tested via `asyncio.run(...)` inside plain sync test functions. The vision HTTP call in `parser.py` uses a plain pooled sync `httpx.Client`, not shared with `generator.py`'s async client (different call context; sharing would require making the whole upload path async for no behavioral benefit).
- Full test suite must pass after every task.
- **Environment:** there is one real Python environment for this project, at the absolute path `/home/haven/Code/sci-papers-summarizer/.venv`. Do NOT run `uv sync` or `uv run` from inside this worktree — `uv` resolves against whatever `pyproject.toml` it finds in the current directory tree, and since this worktree has its own copy of that file, `uv sync`/`uv run` here can silently rewrite a *different* environment than the one you intend, or create a stray local `.venv` that drifts from the real one. Instead:
  - Run tests with: `/home/haven/Code/sci-papers-summarizer/.venv/bin/python -m pytest <args>`
  - Install a new dependency with: `/home/haven/Code/sci-papers-summarizer/.venv/bin/python -m pip install <package>` (installs/updates only the named package — it will not reconcile or remove anything else, unlike `uv sync`).

---

### Task 1: Delete dead code and resolve the duplicate project scaffold

**Files:**
- Delete: `src/pyproject.toml`, `src/uv.lock`, `src/README.md`
- Delete (directory, gitignored, not tracked): `src/.venv`
- Modify: `pyproject.toml` (root) — drop `marker-pdf`, add `pymupdf`/`pillow`, add `[tool.pytest.ini_options]`
- Modify: `.env` — remove `SURYA_INFERENCE_BACKEND`, `LLAMA_CPP_BINARY`, and the commented-out OpenRouter block
- Modify: `src/services/chunker.py:154-156` — delete dead `chunk_text()` (zero callers)

**Interfaces:**
- Produces: a `live_api` pytest marker (replacing the old `marker` marker name, since `marker-pdf` no longer exists in this project) registered in root `pyproject.toml`, deselected by default via `addopts`.

- [ ] **Step 1: Confirm `chunk_text` has no callers**

Run: `grep -rn "chunk_text(" /home/haven/Code/sci-papers-summarizer/src --include='*.py'`
Expected: only the definition line in `chunker.py` (no call sites).

- [ ] **Step 2: Delete `chunk_text()` from `src/services/chunker.py`**

Remove lines 153-156 (the trailing compat alias):

```python
def chunk_text(text: str, document_id: str, chunk_size: int = 900, overlap: int = 0) -> list[Chunk]:
    """Compat alias for plain-text ingestion (no headings → section "")."""
    return chunk_markdown(text, document_id)
```

File should now end right after the `chunk_markdown` function's closing `return chunks`.

- [ ] **Step 3: Delete the stale `src/` project scaffold**

```bash
cd /home/haven/Code/sci-papers-summarizer
git rm src/pyproject.toml src/uv.lock src/README.md
rm -rf src/.venv
```

- [ ] **Step 4: Update root `pyproject.toml` dependencies and pytest config**

Replace the `dependencies` list and add a pytest config section:

```toml
[project]
name = "sci-papers-summarizer"
version = "0.1.0"
description = "RAG-based scientific paper summarizer (FastAPI + ChromaDB + Z.ai GLM)"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn>=0.30",
    "chromadb>=0.5",
    "sentence-transformers>=3.0",
    "httpx>=0.27",
    "python-multipart>=0.0.9",
    "pypdf>=4.0",
    "python-dotenv>=1.0",
    "pymupdf>=1.24",
    "pillow>=10.0",
]

[tool.uv]
# Dependency manifest only — the app is run directly, not installed as a package.
package = false

[tool.pytest.ini_options]
markers = ["live_api: hits the real GLM API (run with LLM_API_KEY set and -m live_api)"]
addopts = "-m 'not live_api'"
```

- [ ] **Step 5: Clean up `.env`**

Remove these lines entirely:

```
# Previous provider — uncomment to switch back (also set LLM_BASE_URL
# back to https://openrouter.ai/api/v1)
#OPENROUTER_API_KEY=REDACTED
```

and:

```
# marker's OCR engine (surya) auto-picks the "vllm" backend whenever it
# detects an NVIDIA GPU, which spawns `docker run --runtime nvidia ...`.
# This host's docker has no nvidia runtime configured, so force the
# llama.cpp backend instead — runs locally, no Docker required.
SURYA_INFERENCE_BACKEND=llamacpp
LLAMA_CPP_BINARY=/home/haven/.local/opt/llama.cpp/llama-server
```

`.env` should end up containing only the `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` block (with its existing comment).

- [ ] **Step 6: Install the new dependencies and run the full suite**

```bash
/home/haven/Code/sci-papers-summarizer/.venv/bin/python -m pip install pymupdf pillow
/home/haven/Code/sci-papers-summarizer/.venv/bin/python -m pip uninstall -y marker-pdf
/home/haven/Code/sci-papers-summarizer/.venv/bin/python -m pytest src -q
```

Expected: all tests pass (marker-pdf code paths aren't touched yet, so `test_parser.py`/`test_documents_figures.py` still pass using the old `marker_convert` seam).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore: remove dead chunk_text, stale src/ project scaffold, and unused env vars"
```

---

### Task 2: Pool the GLM chat client in `generator.py`

**Files:**
- Modify: `src/services/generator.py`
- Test: `src/tests/test_generator.py` (new)

**Interfaces:**
- Produces: `generator.get_client() -> httpx.AsyncClient` (module-level singleton), `generator.aclose_client() -> None` (async, resets the singleton).
- Consumes: nothing new.

- [ ] **Step 1: Write the failing test**

Create `src/tests/test_generator.py`:

```python
import asyncio

from src.services import generator


def test_get_client_returns_same_instance_until_closed():
    generator._client = None
    first = generator.get_client()
    second = generator.get_client()
    assert first is second
    asyncio.run(generator.aclose_client())


def test_aclose_client_resets_singleton():
    generator._client = None
    generator.get_client()
    asyncio.run(generator.aclose_client())
    assert generator._client is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/haven/Code/sci-papers-summarizer/.venv/bin/python -m pytest src/tests/test_generator.py -v`
Expected: FAIL with `AttributeError: module 'src.services.generator' has no attribute '_client'` (or `get_client`).

- [ ] **Step 3: Implement the pooled client in `generator.py`**

Replace the top of `src/services/generator.py` (keep `json`/`os`/`AsyncIterator`/`httpx` imports and the `MODEL`/`BASE_URL` lines) by inserting this block right after `BASE_URL = ...` and before `require_api_key`:

```python
_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    """Return the shared streaming client, creating it on first use."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=None)
    return _client


async def aclose_client() -> None:
    """Close the shared client; called on app shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
```

Then change `stream_answer` to use the pooled client instead of opening its own, and **dedent the whole body by one level (4 spaces)** since the outer `async with` is gone. Replace the entire function body (everything from `async with httpx.AsyncClient` to the end of the function) with:

```python
    client = get_client()
    async with client.stream(
        "POST",
        f"{BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {require_api_key()}"},
        json={
            "model": MODEL,
            "stream": True,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        },
    ) as response:
        if response.is_error:
            # Keep the provider's explanation (rate limits, bad key, model
            # issues) instead of a bare status code.
            body = (await response.aread()).decode(errors="replace")
            try:
                error = json.loads(body).get("error", {})
                # metadata.raw (OpenRouter) or error.message (Z.ai) carry
                # the actionable upstream message (e.g. rate limits).
                detail = (
                    error.get("metadata", {}).get("raw")
                    or error.get("message")
                    or body[:200]
                )
            except ValueError:
                detail = body[:200]
            raise httpx.HTTPStatusError(
                f"{response.status_code} {response.reason_phrase}: "
                f"{detail or response.reason_phrase}",
                request=response.request,
                response=response,
            )
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            data = line[len("data: ") :]
            if data == "[DONE]":
                break
            event = json.loads(data)
            # Providers append annotation events (usage stats) with an
            # empty choices list — skip them instead of indexing [0].
            choices = event.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta", {}).get("content")
            if delta:
                yield delta
```

Every line here is one indentation level shallower than in the current file (the old outer `async with httpx.AsyncClient(timeout=None) as client:` wrapper is gone, so everything that was nested inside it moves left by 4 spaces).

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/haven/Code/sci-papers-summarizer/.venv/bin/python -m pytest src/tests/test_generator.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Wire shutdown cleanup into the app**

In `src/main.py`, add this after the `health_check` function (before the `FRONTEND_DIST` block):

```python
@src.on_event("shutdown")
async def _close_llm_client():
    from src.services.generator import aclose_client

    await aclose_client()
```

- [ ] **Step 6: Run the full suite**

Run: `/home/haven/Code/sci-papers-summarizer/.venv/bin/python -m pytest -q`
Expected: all tests pass, including the new `test_generator.py`.

- [ ] **Step 7: Commit**

```bash
git add src/services/generator.py src/main.py src/tests/test_generator.py
git commit -m "perf: pool the GLM chat client instead of opening one per request"
```

---

### Task 3: Render PDF pages to images with PyMuPDF

**Files:**
- Modify: `src/services/parser.py`
- Test: `src/tests/test_parser.py`

**Interfaces:**
- Produces: `parser.render_pages(pdf_path: str, dpi: int = 150) -> list[PIL.Image.Image]`.
- Consumes: nothing new (uses `pymupdf`/`fitz` and `Pillow`, both added to `pyproject.toml` in Task 1).

- [ ] **Step 1: Write the failing test**

Add to `src/tests/test_parser.py` (near the top, after the existing imports):

```python
def test_render_pages_returns_one_image_per_pdf_page(tmp_path: Path):
    from pypdf import PdfWriter
    from PIL import Image

    pdf = tmp_path / "doc.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_blank_page(width=612, height=792)
    with pdf.open("wb") as fh:
        writer.write(fh)

    pages = parser.render_pages(str(pdf))
    assert len(pages) == 2
    assert all(isinstance(p, Image.Image) for p in pages)
    assert pages[0].width > 0 and pages[0].height > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/haven/Code/sci-papers-summarizer/.venv/bin/python -m pytest src/tests/test_parser.py::test_render_pages_returns_one_image_per_pdf_page -v`
Expected: FAIL with `AttributeError: module 'src.services.parser' has no attribute 'render_pages'`.

- [ ] **Step 3: Implement `render_pages` in `parser.py`**

Add this function to `src/services/parser.py`, after the `ParsedDocument` dataclass and before the (soon to be removed) `_converter`/`marker_convert` block:

```python
def render_pages(pdf_path: str, dpi: int = 150) -> list["Image.Image"]:
    """Rasterize each PDF page to an image. Pure rendering — no ML model."""
    import fitz  # pymupdf
    from PIL import Image

    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)
    doc = fitz.open(pdf_path)
    try:
        return [
            Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            for pix in (page.get_pixmap(matrix=matrix) for page in doc)
        ]
    finally:
        doc.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/haven/Code/sci-papers-summarizer/.venv/bin/python -m pytest src/tests/test_parser.py::test_render_pages_returns_one_image_per_pdf_page -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/services/parser.py src/tests/test_parser.py
git commit -m "feat: render PDF pages to images with PyMuPDF"
```

---

### Task 4: Add the GLM vision call and its data shapes

**Files:**
- Modify: `src/services/parser.py`
- Test: `src/tests/test_parser.py`

**Interfaces:**
- Produces: `parser.FigureRegion(bbox: tuple[float, float, float, float], caption: str = "")`, `parser.PageResult(markdown: str, figures: list[FigureRegion])`, `parser.vision_parse_page(image: PIL.Image.Image) -> PageResult`, `parser._get_vision_client() -> httpx.Client` (monkeypatch seam).
- Consumes: `generator.BASE_URL`, `generator.MODEL`, `generator.require_api_key()` from Task 2's unchanged `generator.py` exports (reused, not duplicated).

- [ ] **Step 1: Write the failing test**

Add to `src/tests/test_parser.py`:

```python
def test_vision_parse_page_parses_markdown_and_figures(monkeypatch):
    import json as json_module
    from PIL import Image

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json_module.dumps(
                                {
                                    "markdown": "# Intro\n\ntext",
                                    "figures": [
                                        {"bbox": [0, 0, 10, 10], "caption": "Figure 1: a plot"}
                                    ],
                                }
                            )
                        }
                    }
                ]
            }

    class FakeClient:
        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(parser, "_get_vision_client", lambda: FakeClient())
    image = Image.new("RGB", (100, 100))
    result = parser.vision_parse_page(image)
    assert result.markdown == "# Intro\n\ntext"
    assert result.figures == [parser.FigureRegion(bbox=(0, 0, 10, 10), caption="Figure 1: a plot")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/haven/Code/sci-papers-summarizer/.venv/bin/python -m pytest src/tests/test_parser.py::test_vision_parse_page_parses_markdown_and_figures -v`
Expected: FAIL with `AttributeError: module 'src.services.parser' has no attribute 'vision_parse_page'`.

- [ ] **Step 3: Implement the vision call in `parser.py`**

Add these imports at the top of `src/services/parser.py` (alongside the existing `from dataclasses import dataclass, field` and `from pathlib import Path`):

```python
import base64
import io
import json

import httpx

from src.services.generator import BASE_URL, MODEL, require_api_key
```

Add these dataclasses right after `ParsedDocument`:

```python
@dataclass
class FigureRegion:
    bbox: tuple[float, float, float, float]
    caption: str = ""


@dataclass
class PageResult:
    markdown: str
    figures: list[FigureRegion] = field(default_factory=list)
```

Add the prompt, client seam, and call function (after `render_pages`, before `parse_pdf_file`):

```python
VISION_PROMPT = (
    "You are converting one page of a scanned academic paper into structured "
    "data. Return ONLY a JSON object (no markdown code fences, no commentary) "
    "with exactly two keys: \"markdown\" (the page's content as GitHub-flavored "
    "markdown, preserving heading levels with # syntax) and \"figures\" (a JSON "
    "array of objects with \"bbox\": [x0, y0, x1, y1] in this image's pixel "
    "coordinates and \"caption\": the figure or table's caption text, for every "
    "figure or table on the page; an empty array if there are none)."
)

_vision_client: httpx.Client | None = None


def _get_vision_client() -> httpx.Client:
    global _vision_client
    if _vision_client is None:
        _vision_client = httpx.Client(timeout=120)
    return _vision_client


def vision_parse_page(image: "Image.Image") -> PageResult:
    """Send one page image to the configured GLM model and parse its reply.

    Kept as a module-level seam so tests can monkeypatch it.
    """
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode()

    response = _get_vision_client().post(
        f"{BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {require_api_key()}"},
        json={
            "model": MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": VISION_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{encoded}"},
                        },
                    ],
                }
            ],
        },
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    data = json.loads(content)
    figures = [
        FigureRegion(bbox=tuple(figure["bbox"]), caption=figure.get("caption", ""))
        for figure in data.get("figures", [])
    ]
    return PageResult(markdown=data["markdown"], figures=figures)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/haven/Code/sci-papers-summarizer/.venv/bin/python -m pytest src/tests/test_parser.py::test_vision_parse_page_parses_markdown_and_figures -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/services/parser.py src/tests/test_parser.py
git commit -m "feat: parse page images into markdown and figure regions via GLM vision"
```

---

### Task 5: Rewrite `parse_pdf_file` and remove marker entirely

**Files:**
- Modify: `src/services/parser.py` — remove `_converter`/`marker_convert`, rewrite `parse_pdf_file`
- Modify: `src/tests/test_parser.py` — replace the two marker-specific tests

**Interfaces:**
- Produces: `parser.parse_pdf_file(file_path: str, figures_dir: str | None = None) -> ParsedDocument` (same signature as before; internals changed).
- Consumes: `render_pages` (Task 3), `vision_parse_page`/`PageResult`/`FigureRegion` (Task 4).

- [ ] **Step 1: Write the failing test — replace `test_pdf_uses_marker_and_saves_figures`**

In `src/tests/test_parser.py`, delete this existing test:

```python
def test_pdf_uses_marker_and_saves_figures(tmp_path: Path, monkeypatch):
    fig_dir = tmp_path / "figures"

    class FakeImage:
        def save(self, path):
            Path(path).write_bytes(b"png")

    def fake_convert(pdf_path):
        return ("# T\n\ntext\n\n![f](fig1.png)\n", {"fig1.png": FakeImage()})

    monkeypatch.setattr(parser, "marker_convert", fake_convert)
    doc = parser.parse_file("whatever.pdf", figures_dir=str(fig_dir))
    assert doc.markdown.startswith("# T")
    assert [f.name for f in doc.figures] == ["fig1.png"]
    assert (fig_dir / "fig1.png").exists()
```

Replace it with:

```python
def test_pdf_pages_are_rendered_and_figures_saved(tmp_path: Path, monkeypatch):
    fig_dir = tmp_path / "figures"

    class FakeImage:
        def crop(self, box):
            return self

        def save(self, path):
            Path(path).write_bytes(b"png")

    fake_page = FakeImage()

    def fake_render_pages(pdf_path):
        return [fake_page]

    def fake_vision_parse_page(image):
        return parser.PageResult(
            markdown="# T\n\ntext",
            figures=[parser.FigureRegion(bbox=(0, 0, 1, 1), caption="Figure 1: a plot")],
        )

    monkeypatch.setattr(parser, "render_pages", fake_render_pages)
    monkeypatch.setattr(parser, "vision_parse_page", fake_vision_parse_page)
    doc = parser.parse_file("whatever.pdf", figures_dir=str(fig_dir))
    assert doc.markdown.startswith("# T")
    assert [f.name for f in doc.figures] == ["page0_fig0.png"]
    assert (fig_dir / "page0_fig0.png").exists()
```

Also delete the old `test_real_marker_conversion` test:

```python
@pytest.mark.marker
def test_real_marker_conversion(tmp_path: Path):
    pytest.importorskip("pypdf")
    from pypdf import PdfWriter

    pdf = tmp_path / "doc.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with pdf.open("wb") as fh:
        writer.write(fh)
    doc = parser.parse_file(str(pdf), figures_dir=str(tmp_path / "figs"))
    assert isinstance(doc.markdown, str)
```

Replace it with a real-API equivalent, guarded by the `live_api` marker from Task 1 and skipped when no key is configured:

```python
@pytest.mark.live_api
def test_real_glm_vision_conversion(tmp_path: Path):
    import os

    if not os.environ.get("LLM_API_KEY"):
        pytest.skip("LLM_API_KEY not set")
    pytest.importorskip("pypdf")
    from pypdf import PdfWriter

    pdf = tmp_path / "doc.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with pdf.open("wb") as fh:
        writer.write(fh)
    doc = parser.parse_file(str(pdf), figures_dir=str(tmp_path / "figs"))
    assert isinstance(doc.markdown, str)
```

- [ ] **Step 2: Run the new test to verify it fails**

Run: `/home/haven/Code/sci-papers-summarizer/.venv/bin/python -m pytest src/tests/test_parser.py::test_pdf_pages_are_rendered_and_figures_saved -v`
Expected: FAIL — `parse_pdf_file` still calls the (soon to be deleted) `marker_convert`, so `render_pages`/`vision_parse_page` are never invoked and the assertions on `page0_fig0.png` fail.

- [ ] **Step 3: Remove `marker_convert` and rewrite `parse_pdf_file`**

In `src/services/parser.py`, delete the `_converter` global and the whole `marker_convert` function:

```python
_converter = None  # marker models are heavy — load once per process


def marker_convert(pdf_path: str) -> tuple[str, dict]:
    """Run marker and return (markdown, {image_name: PIL.Image}).

    Kept as a module-level seam so tests can monkeypatch it.
    """
    global _converter
    if _converter is None:
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict

        _converter = PdfConverter(artifact_dict=create_model_dict())
    rendered = _converter(pdf_path)
    from marker.output import text_from_rendered

    text, _, images = text_from_rendered(rendered)
    return text, images
```

Replace the existing `parse_pdf_file` function:

```python
def parse_pdf_file(file_path: str, figures_dir: str | None = None) -> ParsedDocument:
    markdown, images = marker_convert(file_path)
    figures: list[Figure] = []
    if images and figures_dir:
        out = Path(figures_dir)
        out.mkdir(parents=True, exist_ok=True)
        for name, image in images.items():
            safe = Path(name).name  # marker controls names; sanitize anyway
            image.save(str(out / safe))
            figures.append(Figure(name=safe))
    return ParsedDocument(markdown=markdown, figures=figures)
```

with:

```python
def parse_pdf_file(file_path: str, figures_dir: str | None = None) -> ParsedDocument:
    pages = render_pages(file_path)
    out = Path(figures_dir) if figures_dir else None
    if out:
        out.mkdir(parents=True, exist_ok=True)

    markdown_blocks: list[str] = []
    figures: list[Figure] = []
    for page_index, page_image in enumerate(pages):
        result = vision_parse_page(page_image)
        markdown_blocks.append(result.markdown)
        for fig_index, region in enumerate(result.figures):
            name = f"page{page_index}_fig{fig_index}.png"
            if out:
                box = tuple(int(v) for v in region.bbox)
                page_image.crop(box).save(str(out / name))
            caption = region.caption or name
            markdown_blocks.append(f"![{caption}]({name})\n\n{region.caption}".strip())
            figures.append(Figure(name=name, caption=region.caption))
    return ParsedDocument(markdown="\n\n".join(markdown_blocks), figures=figures)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/home/haven/Code/sci-papers-summarizer/.venv/bin/python -m pytest src/tests/test_parser.py -v`
Expected: all tests in the file PASS (the `live_api` one is skipped by default per the `addopts` from Task 1).

- [ ] **Step 5: Commit**

```bash
git add src/services/parser.py src/tests/test_parser.py
git commit -m "feat: replace marker's local OCR stack with GLM vision calls"
```

---

### Task 6: Update the figures-upload test seam and final verification

**Files:**
- Modify: `src/tests/test_documents_figures.py`

**Interfaces:**
- Consumes: `parser.render_pages`, `parser.vision_parse_page`, `parser.PageResult`, `parser.FigureRegion` from Tasks 3-5.

- [ ] **Step 1: Write the failing test change**

In `src/tests/test_documents_figures.py`, replace `test_upload_stores_figure_and_serves_it`'s monkeypatch block:

```python
def test_upload_stores_figure_and_serves_it(client, monkeypatch):
    from src.services import parser

    class FakeImage:
        def save(self, path):
            Path(path).write_bytes(b"fakepng")

    def fake_convert(pdf_path):
        return ("# Paper\n\n![f](fig1.png)\n\nFigure 1: A curve.\n", {"fig1.png": FakeImage()})

    monkeypatch.setattr(parser, "marker_convert", fake_convert)
    monkeypatch.setattr("src.routers.documents.embed_text", lambda t: [0.1, 0.2])
```

with:

```python
def test_upload_stores_figure_and_serves_it(client, monkeypatch):
    from src.services import parser

    class FakeImage:
        def crop(self, box):
            return self

        def save(self, path):
            Path(path).write_bytes(b"fakepng")

    def fake_render_pages(pdf_path):
        return [FakeImage()]

    def fake_vision_parse_page(image):
        return parser.PageResult(
            markdown="# Paper",
            figures=[parser.FigureRegion(bbox=(0, 0, 1, 1), caption="Figure 1: A curve.")],
        )

    monkeypatch.setattr(parser, "render_pages", fake_render_pages)
    monkeypatch.setattr(parser, "vision_parse_page", fake_vision_parse_page)
    monkeypatch.setattr("src.routers.documents.embed_text", lambda t: [0.1, 0.2])
```

The test's assertion `assert res.json()["chunks"] == 1` stays valid: one page produces one figure chunk (the markdown-only text from `"# Paper"` is too short on its own to be a separate chunk and merges with nothing else, while the figure block is always isolated into its own chunk by `chunker.py`'s flush-on-figure logic — same behavior as the pre-existing test).

- [ ] **Step 2: Run test to verify it fails, then passes**

Run: `/home/haven/Code/sci-papers-summarizer/.venv/bin/python -m pytest src/tests/test_documents_figures.py -v`
Expected (before Task 3-5 were applied, this would fail; since they're already done, it should): PASS. If it fails on the chunk-count assertion, inspect `res.json()["chunk_preview"]` to see the actual chunk text/count and adjust the fake figure/caption text rather than the production code.

- [ ] **Step 3: Run the entire suite**

```bash
cd /home/haven/Code/sci-papers-summarizer
/home/haven/Code/sci-papers-summarizer/.venv/bin/python -m pytest -q
```

Expected: all tests pass (live-API test skipped by default).

- [ ] **Step 4: Commit**

```bash
git add src/tests/test_documents_figures.py
git commit -m "test: update figures-upload fixture for the GLM vision parser seam"
```
