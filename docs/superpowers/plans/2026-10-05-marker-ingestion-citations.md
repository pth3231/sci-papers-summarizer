# Marker Ingestion + Validated Citations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild ingestion on marker-pdf (markdown with LaTeX equations/tables, extracted figures, section-aware chunks) and add validated inline `[n]` citations with KaTeX rendering in the chat UI.

**Architecture:** The pipeline shape is unchanged (upload → parse → chunk → embed → store; chat → retrieve → generate). Parser returns a structured `ParsedDocument`; the chunker walks markdown headings and packs paragraphs within a MiniLM-safe budget; chunk metadata gains `section`/`kind`/`figure_path` in a new `documents_v2` chroma collection; the chat router numbers excerpts and instructs the model to cite; the frontend linkifies `[n]` markers as chips, renders KaTeX math, displays cited figures, and flags hallucinated markers.

**Tech Stack:** Python 3.12 + uv (backend in `src/`), marker-pdf (programmatic `PdfConverter`), chromadb, sentence-transformers (MiniLM unchanged), pytest (new); React 19 + react-markdown@10 + remark-math@6 + rehype-katex@7 + katex@0.16.

**Spec:** `docs/superpowers/specs/2026-10-05-citations-parser-chunker-design.md`

## Global Constraints

- Backend runs from `src/` (`uv run fastapi dev`); deps go in `src/pyproject.toml` (the live manifest) AND are mirrored in the root `pyproject.toml` description-project for parity.
- Chunk budget: target 600–900 chars, hard max 1000 (MiniLM truncates ~256 tokens). Never split mid-sentence except oversized paragraphs (split on sentence boundaries then).
- Chroma collection name: `documents_v2` (old `documents` collection orphaned; users re-upload).
- Figure files live under `uploads/<document_id>/figures/`; served by `GET /documents/{id}/figures/{name}` with `Path(name).name` sanitization (no path traversal).
- Marker programmatic API (verified): `PdfConverter(artifact_dict=create_model_dict())` → `rendered = converter(pdf_path)` → `text, ext, images = text_from_rendered(rendered)`; `images` is `{name: PIL.Image}`. Load models once (module-level lazy singleton) — model load is seconds, not per-request.
- LLM env vars: `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL` (do not rename).
- Frontend markdown stack: `react-markdown@^10.1.0`, `remark-gfm@^4`, `remark-breaks@^4`; add `remark-math@^6`, `rehype-katex@^7`, `katex@^0.16`. No rehype-raw/rehype-sanitize (citation chips are done via markdown-link transform + `components.a` override instead — keeps KaTeX classes intact).
- Git: local commits only; **never** `git push` or `git merge`.
- Marker model tests are hermetic: unit tests monkeypatch the marker wrapper; a real-marker test is `@pytest.mark.marker` and skipped unless `MARKER_INTEGRATION=1` (avoids 2–4GB downloads in the test cycle).
- Commit message style: `feat:`/`test:`/`docs:` prefixes, end with `Co-Authored-By: Claude <noreply@anthropic.com>`.

## File Structure

| File | Responsibility |
|---|---|
| `src/services/parser.py` (modify) | marker/pypdf→marker + txt → `ParsedDocument(markdown, figures)` |
| `src/services/chunker.py` (rewrite) | markdown → structure-aware `Chunk` list |
| `src/database/vector_store.py` (modify) | `documents_v2` collection, extended metadata |
| `src/routers/documents.py` (modify) | figures wiring + figure-serving endpoint |
| `src/routers/chat.py` (modify) | numbered context, citation prompt, rich `X-Sources` |
| `src/view/src/lib/api.ts` (modify) | richer `SourceExcerpt`, figure URL prefixing |
| `src/view/src/types.ts` (modify) | `SourceExcerpt` fields, `Message.citations` |
| `src/view/src/App.tsx` (modify) | post-stream citation extraction |
| `src/view/src/components/ChatPanel.tsx` (modify) | KaTeX pipeline, chips, sources/figure rendering |
| `src/view/src/App.css` (modify) | chip + figure + uncited styles |
| `src/tests/` (new) | backend unit/integration tests |

---

## Phase 1 — Ingestion foundation

### Task 1: Backend test scaffolding

**Files:**
- Modify: `src/pyproject.toml` (dev dep)
- Create: `src/tests/__init__.py` (empty), `src/tests/test_smoke.py`

**Interfaces:**
- Produces: runnable `pytest` from `src/` — all later tasks use it.

- [ ] **Step 1: Add pytest as a dev dependency**

```bash
cd /home/haven/Code/sci-papers-summarizer/src && uv add --dev pytest
```

- [ ] **Step 2: Create the smoke test**

`src/tests/test_smoke.py`:
```python
def test_services_importable():
    from src.services import chunker, parser  # noqa: F401

def test_routers_importable():
    from src.routers import chat, documents  # noqa: F401
```

`src/tests/__init__.py`: empty file.

- [ ] **Step 3: Run tests**

Run: `cd src && uv run pytest tests/ -q`
Expected: `2 passed` (imports prove the app modules load standalone).

- [ ] **Step 4: Commit**

```bash
git add src/pyproject.toml src/uv.lock src/tests/
git commit -m "test: add pytest scaffolding for the backend

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Structure-aware chunker (chunker.py rewrite)

**Files:**
- Modify: `src/services/chunker.py` (full rewrite)
- Test: `src/tests/test_chunker.py`

**Interfaces:**
- Produces: `Chunk(chunk_id, document_id, text, chunk_index, section, kind, figure_path)` — `section: str` ("" when unknown), `kind: "text"|"figure"`, `figure_path: str|None`. Function `chunk_markdown(markdown: str, document_id: str, min_size: int = 600, max_size: int = 900) -> list[Chunk]`. Keeps a `chunk_text(...)` alias calling `chunk_markdown` for the .txt path (txt has no headings — everything lands in section "").
- Consumes: nothing new (pure function over markdown text).

- [ ] **Step 1: Write the failing tests**

`src/tests/test_chunker.py`:
```python
from src.services.chunker import chunk_markdown

def build(doc_id="d1", **kw):
    return chunk_markdown(KW_MARKDOWN, doc_id, **kw)

KW_MARKDOWN = """# Intro

Alpha paragraph about introductions that is long enough to stand alone here.

## Methods

Beta paragraph one about methods and training procedures in detail.

Beta paragraph two continues the discussion with more analysis.

![Figure 3 caption ref](figures/fig3.png)

Figure 3: Training loss curve across epochs.

### Training

Gamma paragraph nested under a subheading for packing checks.
"""

def test_sections_track_heading_path():
    chunks = build()
    assert any(c.section == "Intro" for c in chunks)
    assert any(c.section == "Methods" for c in chunks)
    assert any(c.section == "Methods > Training" for c in chunks)

def test_paragraphs_packed_within_budget():
    chunks = [c for c in build() if c.kind == "text"]
    assert all(len(c.text) <= 900 for c in chunks)
    # two short paragraphs in the same section merge into one chunk
    methods = [c for c in chunks if c.section == "Methods" and "Beta paragraph" in c.text]
    assert len(methods) == 1 and "Beta paragraph two" in methods[0].text

def test_oversized_paragraph_splits_on_sentences():
    long_para = ("One sentence here. " * 80).strip()  # ~1440 chars
    md = f"# S\n\n{long_para}\n"
    chunks = [c for c in chunk_markdown(md, "d") if c.kind == "text"]
    assert len(chunks) >= 2
    assert all(len(c.text) <= 900 for c in chunks)
    joined = "".join(c.text for c in chunks)
    assert "One sentence here" in joined  # nothing dropped

def test_image_paragraph_becomes_figure_chunk_with_caption():
    chunks = build()
    figs = [c for c in chunks if c.kind == "figure"]
    assert len(figs) == 1
    assert figs[0].figure_path == "figures/fig3.png"
    assert "Figure 3: Training loss curve" in figs[0].text
    assert figs[0].section == "Methods"

def test_chunk_ids_and_indices():
    chunks = build()
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert all(c.chunk_id == f"d1_chunk_{c.chunk_index}" for c in chunks)

def test_plain_text_passthrough():
    chunks = chunk_markdown("just text\n\nmore text\n", "d9")
    assert all(c.section == "" and c.kind == "text" for c in chunks)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src && uv run pytest tests/test_chunker.py -q`
Expected: FAIL — `chunk_markdown` does not exist / `Chunk` lacks fields.

- [ ] **Step 3: Implement the chunker**

`src/services/chunker.py` (replace entire file):
```python
import re
from dataclasses import dataclass

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
IMAGE_LINE_RE = re.compile(r"^!\[[^\]]*\]\(([^)\s]+)[^)]*\)\s*$")
FIGURE_CAPTION_RE = re.compile(r"^(figure|fig\.?|table)\s*\d+", re.IGNORECASE)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

MIN_CHUNK = 600
MAX_CHUNK = 900


@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    text: str
    chunk_index: int
    section: str = ""
    kind: str = "text"  # "text" | "figure"
    figure_path: str | None = None


def _split_blocks(markdown: str) -> list[str]:
    """Split into blank-line-separated blocks; fenced code stays atomic."""
    blocks, current, fenced = [], [], False
    for line in markdown.splitlines():
        if line.strip().startswith("```"):
            fenced = not fenced
            current.append(line)
            continue
        if not line.strip() and not fenced and current:
            blocks.append("\n".join(current))
            current = []
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def chunk_markdown(
    markdown: str, document_id: str, min_size: int = MIN_CHUNK, max_size: int = MAX_CHUNK
) -> list[Chunk]:
    if max_size <= 0:
        raise ValueError("max_size must be greater than 0")

    # Collect (text, section, figure_path) paragraphs first.
    section_path: list[str] = []
    paragraphs: list[tuple[str, str, str | None]] = []
    blocks = _split_blocks(markdown)
    for i, block in enumerate(blocks):
        heading = HEADING_RE.match(block)
        if heading and "\n" not in block:
            level, title = len(heading.group(1)), heading.group(2).strip()
            section_path = section_path[: level - 1]
            section_path.append(title)
            continue
        section = " > ".join(section_path)
        image = IMAGE_LINE_RE.match(block.strip())
        if image:
            caption = ""
            if i + 1 < len(blocks) and FIGURE_CAPTION_RE.match(blocks[i + 1].strip()):
                caption = blocks[i + 1].strip()
            paragraphs.append((f"{block.strip()}\n\n{caption}".strip(), section, image.group(1)))
        elif not FIGURE_CAPTION_RE.match(block.strip()) or not paragraphs or paragraphs[-1][2] is None:
            # skip pure-caption blocks only when they followed an image (already consumed)
            paragraphs.append((block.strip(), section, None))
        else:
            continue

    # Pack paragraphs into chunks.
    chunks: list[Chunk] = []
    buffer: list[tuple[str, str | None]] = []  # (text, figure_path) — one section at a time
    buffer_section = ""

    def flush():
        nonlocal buffer
        if not buffer:
            return
        text = "\n\n".join(part for part, _ in buffer)
        fig = next((fp for _, fp in buffer if fp), None)
        chunks.append(
            Chunk(
                chunk_id=f"{document_id}_chunk_{len(chunks)}",
                document_id=document_id,
                text=text,
                chunk_index=len(chunks),
                section=buffer_section,
                kind="figure" if fig else "text",
                figure_path=fig,
            )
        )
        buffer = []

    for text, section, figure_path in paragraphs:
        if section != buffer_section and buffer:
            flush()
        buffer_section = section
        candidate = "\n\n".join([*[p for p, _ in buffer], text])
        if len(candidate) <= max_size:
            buffer.append((text, figure_path))
            continue
        flush()  # emit what we have without this paragraph
        if len(text) <= max_size:
            buffer.append((text, figure_path))
        else:
            # Oversized paragraph: split on sentence boundaries.
            sentences = SENTENCE_SPLIT_RE.split(text)
            piece = ""
            for sentence in sentences:
                if piece and len(piece) + 1 + len(sentence) > max_size:
                    buffer.append((piece, figure_path if piece.startswith(text[:20]) else None))
                    flush()
                    piece = sentence
                else:
                    piece = f"{piece} {sentence}".strip()
            if piece:
                buffer.append((piece, None))
                flush()
    flush()

    # Re-index (flush order guarantees it, but be explicit).
    for i, chunk in enumerate(chunks):
        chunk.chunk_index = i
        chunk.chunk_id = f"{document_id}_chunk_{i}"
    return chunks


def chunk_text(text: str, document_id: str, chunk_size: int = 900, overlap: int = 0) -> list[Chunk]:
    """Compat alias for plain-text ingestion (no headings → section "")."""
    return chunk_markdown(text, document_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src && uv run pytest tests/test_chunker.py -q`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add src/services/chunker.py src/tests/test_chunker.py
git commit -m "feat: markdown structure-aware chunker with sections and figure chunks

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Marker-based parser

**Files:**
- Modify: `src/services/parser.py`
- Modify: `src/pyproject.toml` + root `pyproject.toml` (dep)
- Test: `src/tests/test_parser.py`

**Interfaces:**
- Produces: `ParsedDocument(markdown: str, figures: list[Figure])`, `Figure(name: str, caption: str)`; `parse_file(file_path: str, figures_dir: str | None = None) -> ParsedDocument`. Internal `marker_convert(pdf_path: str) -> tuple[str, dict]` (monkeypatch seam).
- Consumes: marker API (`PdfConverter`, `create_model_dict`, `text_from_rendered`).

- [ ] **Step 1: Add the dependency**

```bash
cd /home/haven/Code/sci-papers-summarizer/src && uv add "marker-pdf>=1.0"
```
Mirror in root `pyproject.toml` dependencies list: `"marker-pdf>=1.0",` (keep parity; root manifest is documentation-grade).

- [ ] **Step 2: Write the failing tests**

`src/tests/test_parser.py`:
```python
from pathlib import Path

import pytest

from src.services import parser


def test_txt_file_returns_markdown_without_figures(tmp_path: Path):
    f = tmp_path / "notes.txt"
    f.write_text("hello papers", encoding="utf-8")
    doc = parser.parse_file(str(f))
    assert doc.markdown == "hello papers"
    assert doc.figures == []


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

Register the marker in `src/pyproject.toml` `[tool.pytest.ini_options]`:
```toml
[tool.pytest.ini_options]
markers = ["marker: requires downloaded marker models (run with MARKER_INTEGRATION=1)"]
addopts = "-m 'not marker'"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd src && uv run pytest tests/test_parser.py -q`
Expected: FAIL — `ParsedDocument`/`parse_file` signature missing.

- [ ] **Step 4: Implement the parser**

`src/services/parser.py` (replace entire file):
```python
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Figure:
    name: str
    caption: str = ""


@dataclass
class ParsedDocument:
    markdown: str
    figures: list[Figure] = field(default_factory=list)


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


def parse_text_file(file_path: str) -> ParsedDocument:
    with Path(file_path).open("r", encoding="utf-8") as file:
        return ParsedDocument(markdown=file.read())


def parse_file(file_path: str, figures_dir: str | None = None) -> ParsedDocument:
    if file_path.lower().endswith(".pdf"):
        return parse_pdf_file(file_path, figures_dir)
    return parse_text_file(file_path)
```

- [ ] **Step 5: Run tests**

Run: `cd src && uv run pytest tests/test_parser.py -q`
Expected: `2 passed, 1 deselected` (real-marker test deselected without `MARKER_INTEGRATION=1`).

- [ ] **Step 6: Commit**

```bash
git add src/services/parser.py src/tests/test_parser.py src/pyproject.toml src/uv.lock pyproject.toml
git commit -m "feat: marker-based parser returning markdown plus extracted figures

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Vector store v2

**Files:**
- Modify: `src/database/vector_store.py`
- Test: `src/tests/test_vector_store.py`

**Interfaces:**
- Produces: `add_chunk(chunk_id, text, embedding, document_id, chunk_index, filename=None, section="", kind="text", figure_path=None)`; `search_chunks(query_embedding, top_k=5, document_ids=None)` unchanged shape; collection `documents_v2`.
- Consumes: nothing new.

- [ ] **Step 1: Write the failing test**

`src/tests/test_vector_store.py`:
```python
import pytest

from src.database import vector_store


@pytest.fixture()
def store(tmp_path, monkeypatch):
    import chromadb

    client = chromadb.PersistentClient(path=str(tmp_path))
    collection = client.get_or_create_collection(name="documents_v2")
    monkeypatch.setattr(vector_store, "collection", collection)
    return vector_store


def test_collection_name_is_v2(store):
    assert store.collection.name == "documents_v2"


def test_add_chunk_persists_extended_metadata(store):
    store.add_chunk(
        chunk_id="c1", text="t", embedding=[0.1, 0.2], document_id="d1",
        chunk_index=0, filename="p.pdf", section="Methods", kind="figure",
        figure_path="figures/f1.png",
    )
    got = store.collection.get(ids=["c1"])
    meta = got["metadatas"][0]
    assert meta["section"] == "Methods"
    assert meta["kind"] == "figure"
    assert meta["figure_path"] == "figures/f1.png"


def test_search_scopes_by_document_ids(store):
    store.add_chunk("a", "alpha", [1.0, 0.0], "d1", 0, filename="a.pdf")
    store.add_chunk("b", "beta", [0.0, 1.0], "d2", 0, filename="b.pdf")
    res = store.search_chunks([1.0, 0.0], top_k=2, document_ids=["d2"])
    ids = res["ids"][0]
    assert ids == ["b"]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd src && uv run pytest tests/test_vector_store.py -q`
Expected: FAIL — `add_chunk` rejects `section`/`kind`/`figure_path`; collection still `documents`.

- [ ] **Step 3: Implement**

`src/database/vector_store.py` (replace entire file):
```python
import chromadb

client = chromadb.PersistentClient(path="./chroma_db")
# v2: extended chunk metadata (section/kind/figure_path). The old
# "documents" collection is orphaned — documents must be re-uploaded.
collection = client.get_or_create_collection(name="documents_v2")


def add_chunk(
    chunk_id: str,
    text: str,
    embedding: list[float],
    document_id: str,
    chunk_index: int,
    filename: str | None = None,
    section: str = "",
    kind: str = "text",
    figure_path: str | None = None,
):
    metadata = {
        "document_id": document_id,
        "chunk_index": chunk_index,
        "section": section,
        "kind": kind,
    }
    if filename is not None:
        metadata["filename"] = filename
    if figure_path is not None:
        metadata["figure_path"] = figure_path
    collection.add(
        ids=[chunk_id], documents=[text], embeddings=[embedding], metadatas=[metadata]
    )


def search_chunks(
    query_embedding: list[float], top_k: int = 5, document_ids: list[str] | None = None
):
    return collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where={"document_id": {"$in": document_ids}} if document_ids else None,
    )


def delete_chunks(document_id: str):
    collection.delete(where={"document_id": document_id})
```

- [ ] **Step 4: Run tests**

Run: `cd src && uv run pytest tests/test_vector_store.py -q`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add src/database/vector_store.py src/tests/test_vector_store.py
git commit -m "feat: documents_v2 collection with section/kind/figure_path metadata

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Documents router — figures wiring + serving endpoint

**Files:**
- Modify: `src/routers/documents.py:22-93` (upload handler) and add figure endpoint
- Test: `src/tests/test_documents_figures.py`

**Interfaces:**
- Produces: `GET /documents/{document_id}/figures/{name}` → `FileResponse` (404 when missing); upload stores figures under `uploads/<doc_id>/figures/` and ingests via `chunk_markdown` + extended `add_chunk`.
- Consumes: `parse_file(path, figures_dir)` (Task 3), `chunk_markdown` (Task 2), `add_chunk` extended (Task 4).

- [ ] **Step 1: Write the failing test**

`src/tests/test_documents_figures.py`:
```python
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.main import src as app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("src.routers.documents.UPLOAD_DIR", tmp_path)
    return TestClient(app)


def test_upload_stores_figure_and_serves_it(client, monkeypatch):
    from src.services import parser

    class FakeImage:
        def save(self, path):
            Path(path).write_bytes(b"fakepng")

    def fake_convert(pdf_path):
        return ("# Paper\n\n![f](fig1.png)\n\nFigure 1: A curve.\n", {"fig1.png": FakeImage()})

    monkeypatch.setattr(parser, "marker_convert", fake_convert)
    monkeypatch.setattr("src.routers.documents.embed_text", lambda t: [0.1, 0.2])

    res = client.post(
        "/documents/", files={"file": ("paper.pdf", b"%PDF-fake", "application/pdf")}
    )
    assert res.status_code == 200
    doc_id = res.json()["document_id"]
    assert res.json()["chunks"] == 1  # the figure chunk

    served = client.get(f"/documents/{doc_id}/figures/fig1.png")
    assert served.status_code == 200
    assert served.content == b"fakepng"


def test_figure_name_traversal_is_rejected(client):
    res = client.get("/documents/any/figures/..%2F..%2Fetc%2Fpasswd")
    assert res.status_code in (404, 400)


def test_missing_figure_is_404(client):
    assert client.get("/documents/nope/figures/x.png").status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `cd src && uv run pytest tests/test_documents_figures.py -q`
Expected: FAIL — upload passes no `figures_dir`, no figure endpoint exists.

- [ ] **Step 3: Implement**

In `src/routers/documents.py`, change the ingestion block (`documents.py:44-56`) to:
```python
    try:
        figures_dir = doc_dir / "figures"
        parsed = parse_file(str(file_path), figures_dir=str(figures_dir))
        chunks = chunk_markdown(parsed.markdown, document_id=document_id)
        for chunk in chunks:
            embedding = embed_text(chunk.text)
            add_chunk(
                chunk_id=chunk.chunk_id,
                text=chunk.text,
                embedding=embedding,
                document_id=chunk.document_id,
                chunk_index=chunk.chunk_index,
                filename=filename,
                section=chunk.section,
                kind=chunk.kind,
                figure_path=chunk.figure_path,
            )
```
Update the import at `documents.py:10` from `chunk_text` to `chunk_markdown`, and `parse_file` stays. Add the endpoint after the upload route:
```python
@router.get("/{document_id}/figures/{figure_name}")
def get_figure(document_id: str, figure_name: str):
    safe_name = Path(figure_name).name  # strip any path components
    figure_path = UPLOAD_DIR / document_id / "figures" / safe_name
    if not figure_path.is_file():
        raise HTTPException(status_code=404, detail=f"figure '{safe_name}' not found")
    return FileResponse(figure_path)
```
Add `from fastapi.responses import FileResponse` to the imports.

- [ ] **Step 4: Run all backend tests**

Run: `cd src && uv run pytest tests/ -q`
Expected: all passed ( Tasks 1–5 ).

- [ ] **Step 5: Commit**

```bash
git add src/routers/documents.py src/tests/test_documents_figures.py
git commit -m "feat: store and serve extracted figures per document

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 2 — Citations

### Task 6: Chat backend — numbered excerpts + citation instruction + rich sources

**Files:**
- Modify: `src/routers/chat.py:17-25` (prompt/constants), `:39-65` (retrieval → context/sources)
- Test: `src/tests/test_chat_citations.py`

**Interfaces:**
- Produces: `X-Sources` entries `{index, filename, section, kind, figure_url, excerpt}` (figure_url `None` for text chunks); context lines `[n] (filename — section) text`; system prompt with citation instruction.
- Consumes: `search_chunks` metadata from Task 4.

- [ ] **Step 1: Write the failing tests**

`src/tests/test_chat_citations.py`:
```python
from src.routers.chat import build_context, build_sources


def fake_results():
    return {
        "documents": [["alpha text", "beta caption"]],
        "metadatas": [[
            {"filename": "a.pdf", "section": "Intro", "kind": "text", "document_id": "d1"},
            {"filename": "b.pdf", "section": "Methods", "kind": "figure",
             "figure_path": "figures/f9.png", "document_id": "d2"},
        ]],
    }


def test_context_lines_are_numbered_with_section():
    context = build_context(*_split(fake_results()))
    assert context.splitlines()[0].startswith("[1] (a.pdf — Intro) alpha text")
    assert "[2] (b.pdf — Methods) beta caption" in context


def test_sources_carry_index_section_and_figure_url():
    sources = build_sources(*_split(fake_results()))
    assert sources[0] == {
        "index": 1, "filename": "a.pdf", "section": "Intro", "kind": "text",
        "figure_url": None, "excerpt": "alpha text",
    }
    assert sources[1]["figure_url"] == "/documents/d2/figures/f9.png"
    assert sources[1]["index"] == 2


def _split(results):
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    return docs, metas
```

- [ ] **Step 2: Run to verify failure**

Run: `cd src && uv run pytest tests/test_chat_citations.py -q`
Expected: FAIL — `build_context`/`build_sources` don't exist.

- [ ] **Step 3: Implement**

In `src/routers/chat.py`, extend the system prompt (`chat.py:17-21`) — append one sentence:
```python
SYSTEM_PROMPT = (
    "You are a scientific paper summarizer. Answer the question using the "
    "provided context excerpts from the user's papers when they are relevant. "
    "Prefer concise bullet points. End each bullet or claim with its citation "
    "marker(s), like [1] or [2][5]. Cite only the numbered excerpts provided, "
    "and say so explicitly when the context is insufficient."
)
```
Replace the context and sources construction (`chat.py:47-65`) with:
```python
def build_context(documents: list[str], metadatas: list[dict]) -> str:
    return "\n\n".join(
        f"[{i + 1}] ({meta.get('filename', 'unknown source')} — "
        f"{meta.get('section') or 'no section'}) {text}"
        for i, (text, meta) in enumerate(zip(documents, metadatas))
    )


def build_sources(documents: list[str], metadatas: list[dict]) -> list[dict]:
    sources = []
    for i, (text, meta) in enumerate(zip(documents, metadatas)):
        figure_url = None
        if meta.get("figure_path"):
            from pathlib import Path

            figure_url = (
                f"/documents/{meta.get('document_id')}/figures/"
                f"{Path(meta['figure_path']).name}"
            )
        sources.append(
            {
                "index": i + 1,
                "filename": meta.get("filename", "unknown source"),
                "section": meta.get("section", ""),
                "kind": meta.get("kind", "text"),
                "figure_url": figure_url,
                "excerpt": text[:SOURCE_EXCERPT_LENGTH],
            }
        )
    return sources
```
and in the handler use them:
```python
    context = build_context(documents, metadatas)
    ...
    sources = build_sources(documents, metadatas)
```

- [ ] **Step 4: Run tests**

Run: `cd src && uv run pytest tests/test_chat_citations.py tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/routers/chat.py src/tests/test_chat_citations.py
git commit -m "feat: numbered context excerpts and rich citation sources payload

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: Frontend — KaTeX, citation chips, validated sources, figure display

**Files:**
- Modify: `src/view/package.json` (deps), `src/view/src/types.ts`, `src/view/src/lib/api.ts`, `src/view/src/App.tsx`, `src/view/src/components/ChatPanel.tsx`, `src/view/src/App.css`

**Interfaces:**
- Consumes: `X-Sources` entries from Task 6 (`{index, filename, section, kind, figure_url, excerpt}`).
- Produces: `Message.citations?: {valid: number[]; invalid: number[]}`; `citationize(content, invalid)` linkify transform; `SourceExcerpt` with the new fields.

- [ ] **Step 1: Install dependencies**

```bash
cd /home/haven/Code/sci-papers-summarizer/src/view && npm install remark-math@^6 rehype-katex@^7 katex@^0.16
```

- [ ] **Step 2: Update types**

`src/view/src/types.ts` — replace `SourceExcerpt` and extend `Message`:
```ts
export interface SourceExcerpt {
  index: number
  filename: string
  section: string
  kind: 'text' | 'figure'
  figure_url: string | null
  excerpt: string
}

export interface Message {
  id: string
  role: Role
  content: string
  sources?: SourceExcerpt[]
  /** Set when generation failed — rendered as an error banner, not answer text. */
  error?: string
  /** Post-stream citation validation against msg.sources. */
  citations?: { valid: number[]; invalid: number[] }
}
```

- [ ] **Step 3: Map the sources payload in api.ts**

In `src/view/src/lib/api.ts`, export the API base for asset URLs and keep passthrough field names:
```ts
export const API_BASE_URL = API_BASE
```
(`streamChat` already returns the parsed header array; the new fields flow through unchanged. If `API_BASE` is `''` in production builds, relative figure URLs work same-origin.)

- [ ] **Step 4: Extract citations post-stream in App.tsx**

Add a helper and call it when sources land (`App.tsx`, after `setMessages(... sources ...)` inside `handleSend`):
```ts
const CITATION_RE = /\[(\d{1,3})\](?!\()/g

function extractCitations(content: string, sourceCount: number) {
  const markers = [...content.matchAll(CITATION_RE)].map((m) => Number(m[1]))
  const valid = markers.filter((n) => n >= 1 && n <= sourceCount)
  const invalid = markers.filter((n) => n < 1 || n > sourceCount)
  return { valid, invalid }
}
```
In the success path of `handleSend`:
```ts
      const citations = extractCitations(assistantContent(history), sources.length)
```
where the streamed content is read back from state — simplest: capture it in the `onChunk` accumulator:
```ts
      let streamed = ''
      const sources = await streamChat(
        history,
        (delta) => {
          streamed += delta
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantId ? { ...m, content: m.content + delta } : m)),
          )
        },
        activeDocIds,
      )
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId ? { ...m, sources, citations: extractCitations(streamed, sources.length) } : m,
        ),
      )
```

- [ ] **Step 5: Render chips + KaTeX + figures in ChatPanel.tsx**

`src/view/src/components/ChatPanel.tsx` — new imports:
```tsx
import katex from 'katex'
import 'katex/dist/katex.min.css'
import rehypeKatex from 'rehype-katex'
import remarkMath from 'remark-math'
```
Add the linkify transform and `a` override. Chips are markdown links to `#cite-n` (markdown links can't carry classes, so the `a` override decides styling from the invalid list):
```tsx
// Turn [n] markers into #cite-n links so they survive markdown rendering.
function citationize(content: string): string {
  return content.replace(/\[(\d{1,3})\](?!\()/g, (_m, num: string) => `[${num}](#cite-${num})`)
}
```
In the component:
```tsx
const invalidCites = msg.citations?.invalid ?? []
...
<Markdown
  remarkPlugins={[remarkMath, remarkGfm, remarkBreaks]}
  rehypePlugins={[rehypeKatex]}
  components={{
    a: ({ href, children }) =>
      typeof href === 'string' && href.startsWith('#cite-') ? (
        <a href={href} className={`cite-chip${invalidCites.includes(Number(href.slice(6))) ? ' invalid' : ''}`}>
          {children}
        </a>
      ) : (
        <a href={href} target="_blank" rel="noreferrer">{children}</a>
      ),
  }}
>
  {citationize(msg.content)}
</Markdown>
```
Replace the sources block with the validated version:
```tsx
{msg.role === 'assistant' && msg.sources && msg.sources.length > 0 && (
  <div className="sources-block" id="cite-list">
    <p className="sources-title">Sources</p>
    <ul className="sources-list">
      {msg.sources.map((source) => {
        const cited = msg.citations?.valid.includes(source.index) ?? false
        return (
          <li key={source.index} className={`source-item${cited ? '' : ' uncited'}`}>
            <span className="source-filename">
              [{source.index}] {source.filename}
              {source.section ? ` — ${source.section}` : ''}
            </span>
            {source.kind === 'figure' && source.figure_url && (
              <img
                className="source-figure"
                src={`${API_BASE_URL}${source.figure_url}`}
                alt={source.excerpt}
              />
            )}
            <span className="source-excerpt">{source.excerpt}</span>
          </li>
        )
      })}
    </ul>
  </div>
)}
```
Import `API_BASE_URL` from `'../lib/api'`.

- [ ] **Step 6: Style chips, figures, uncited entries**

Append to `src/view/src/App.css`:
```css
/* Citation chips and figure sources */

.cite-chip {
  display: inline-block;
  margin: 0 1px;
  padding: 0 5px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 0.7rem;
  font-weight: 600;
  line-height: 1.4;
  text-decoration: none;
  vertical-align: super;
}

.cite-chip.invalid {
  background: var(--danger-soft);
  color: var(--danger);
  outline: 1px dashed var(--danger);
}

.source-item.uncited {
  opacity: 0.45;
}

.source-figure {
  margin: 4px 0;
  max-width: 260px;
  border: 1px solid var(--border);
  border-radius: 6px;
}
```

- [ ] **Step 7: Verify the frontend builds and renders math**

Run: `cd src/view && npm run build`
Expected: clean tsc + vite build.

Manual check (dev server): render check with a scratch message — in the browser console on the running app:
```js
document.dispatchEvent(new CustomEvent('x'))
```
is unnecessary — instead visually verify by asking the app a question (backend from Phase 1) and confirming chips + math render. Fallback check without backend: temporarily set an initial `messages` state entry containing `` `E=mc^2` and $$\sum_i i$$ with [1]`` plus one source, confirm rendering, then revert.

- [ ] **Step 8: Commit**

```bash
git add src/view/package.json src/view/package-lock.json src/view/src/
git commit -m "feat: KaTeX math, citation chips with validation, and figure sources in chat

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: Documentation + end-to-end verification

**Files:**
- Modify: `README.md`, `CLAUDE.md`, `src/README.md` (if it documents the pipeline)

- [ ] **Step 1: Update docs**

`README.md` References section: model line already Z.ai; ensure the converter line credits marker (`https://github.com/datalab-to/marker` — already present). Add to "How to run":
```markdown
### First run note
The first PDF upload downloads marker's models (~2–4GB) to the user cache and
can take a few minutes; later uploads run in seconds on GPU.
```
`CLAUDE.md` pipeline section — update step 1 to mention marker + figures + `documents_v2`, and note re-upload requirement.

- [ ] **Step 2: End-to-end verification checklist**

```bash
cd src && uv run pytest tests/ -q          # all backend tests green
cd src && uv run fastapi dev              # backend up
cd src/view && npm run dev                # frontend up
```
Then in the browser:
1. Upload a real paper PDF — expect an upload taking seconds-to-minutes (first run: model download), then chunk count > 0.
2. Ask "What is the main contribution?" — expect bullets ending in `[n]` chips, sources list with sections, cited entries full-opacity.
3. Ask about a figure ("What does Figure 1 show?") — expect a figure chunk cited, image visible in Sources.
4. Ask something unrelated to the papers — expect the model to say context is insufficient (no fabricated chips).

- [ ] **Step 3: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: marker ingestion and citation usage notes

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review (completed during planning)

- **Spec coverage:** parser→T3, chunker budget/sections/figures→T2, store v2→T4, figure serving→T5, numbered context+prompt→T6, chips/validation/figures/KaTeX→T7, migration+docs+E2E→T8 + README notes. MiniLM stays (non-goal). ✔
- **Type consistency:** `Chunk(section, kind, figure_path)` used identically in T5 ingestion and T4 metadata; `build_sources` figure_url consumed by T7 `figure_url` field (snake_case passthrough matches existing `X-Sources` convention). ✔
- **Placeholders:** none — every code step is complete; the one uncertainty (marker flag details) is isolated behind `marker_convert` and covered by the deselected integration test. ✔
