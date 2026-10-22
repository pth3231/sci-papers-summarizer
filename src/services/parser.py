import base64
import io
import json
import os
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from src.services.generator import BASE_URL, require_api_key

# Bump whenever parsing/chunking logic changes meaningfully. Documents whose
# stored chunks carry an older value are flagged stale and lazily re-parsed
# from their original upload before next use (see src.services.ingest),
# instead of requiring a manual delete + re-upload.
PARSER_VERSION = 1

# The chat model (LLM_MODEL, e.g. glm-5.2) is text-only — it rejects any
# non-"text" content block. Vision needs a separate, vision-capable model.
# glm-4v-flash is the lightweight/fast vision tier — fine now that vision is
# only called for the minority of pages direct text extraction can't handle.
VISION_MODEL = os.environ.get("LLM_VISION_MODEL", "glm-4v-flash")

# Direct text extraction (pymupdf) is free and near-instant, so it's always
# tried first. A full page only escalates to a whole-page vision call when
# direct extraction can't be trusted: too little text to be a real content
# page (scanned), or a high density of math symbols (equations as glyphs
# don't extract cleanly as plain text). Embedded images are handled
# separately — see caption_figure_image — without needing full-page vision.
MIN_DIRECT_TEXT_CHARS = int(os.environ.get("LLM_VISION_MIN_TEXT_CHARS", "20"))
MATH_DENSITY_THRESHOLD = float(os.environ.get("LLM_VISION_MATH_DENSITY", "0.02"))
# Greek, superscript/subscript, letterlike symbols, arrows, math operators,
# supplemental math operators.
MATH_CHAR_PATTERN = re.compile(
    "[Ͱ-Ͽ⁰-₟℀-⅏←-⇿∀-⋿⨀-⫿]"
)

# Pages are independent, so process several concurrently instead of one at a
# time — the wall-clock cost of a multi-page upload is dominated by waiting
# on the vision API, not local compute.
VISION_CONCURRENCY = max(1, int(os.environ.get("LLM_VISION_CONCURRENCY", "4")))

# Lower DPI → smaller page images → faster upload/inference per vision call,
# at some cost to small-text legibility. 120 keeps body text readable while
# meaningfully shrinking payloads versus the previous 150.
RENDER_DPI = int(os.environ.get("LLM_VISION_DPI", "120"))

MAX_RETRIES = max(1, int(os.environ.get("LLM_VISION_MAX_RETRIES", "3")))
RETRY_BACKOFF_SECONDS = float(os.environ.get("LLM_VISION_RETRY_BACKOFF", "2"))
# 429 (rate limit) and 5xx are transient — retrying can help. Other 4xx
# (bad request, auth, unknown model) are deterministic; retrying wastes time.
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


@dataclass
class Figure:
    name: str
    caption: str = ""


@dataclass
class ParsedDocument:
    markdown: str
    figures: list[Figure] = field(default_factory=list)


@dataclass
class FigureRegion:
    bbox: tuple[float, float, float, float]
    caption: str = ""


@dataclass
class PageResult:
    markdown: str
    figures: list[FigureRegion] = field(default_factory=list)


@dataclass
class PageInfo:
    text: str
    images: list[tuple[bytes, str]] = field(default_factory=list)  # (image_bytes, ext)


def render_pages(pdf_path: str, dpi: int = RENDER_DPI) -> list["Image.Image"]:
    """Rasterize each PDF page to an image. Pure rendering — no ML model."""
    import pymupdf as fitz  # the `fitz` package name is a deprecated alias
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


def extract_page_info(pdf_path: str) -> list[PageInfo]:
    """For each page, return its direct-extracted text and the raw bytes of
    each embedded image (exactly as stored in the PDF — no rendering). Pure
    pymupdf reads, no ML model."""
    import pymupdf as fitz

    doc = fitz.open(pdf_path)
    try:
        infos = []
        for page in doc:
            images = []
            for img in page.get_images(full=True):
                extracted = doc.extract_image(img[0])
                images.append((extracted["image"], extracted["ext"]))
            infos.append(PageInfo(text=page.get_text(), images=images))
        return infos
    finally:
        doc.close()


def _needs_vision(text: str) -> bool:
    """Whether a page needs a full-page vision call. Embedded images don't
    trigger this on their own — see caption_figure_image."""
    stripped = text.strip()
    if len(stripped) < MIN_DIRECT_TEXT_CHARS:
        return True
    density = len(MATH_CHAR_PATTERN.findall(text)) / len(text)
    return density > MATH_DENSITY_THRESHOLD


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
_vision_client_lock = threading.Lock()


def _get_vision_client() -> httpx.Client:
    global _vision_client
    if _vision_client is None:
        with _vision_client_lock:
            if _vision_client is None:
                _vision_client = httpx.Client(timeout=120)
    return _vision_client


def close_vision_client() -> None:
    global _vision_client
    if _vision_client is not None:
        _vision_client.close()
        _vision_client = None


def _post_with_retry(client: httpx.Client, url: str, **kwargs) -> httpx.Response:
    """POST with exponential-backoff retry on transient failures (timeouts,
    connection errors, 429 rate limits, 5xx). Deterministic client errors
    (e.g. 400 bad request, unknown model) are returned on the first attempt —
    retrying can't fix those, so there's no point delaying the failure.
    """
    response: httpx.Response | None = None
    for attempt in range(MAX_RETRIES):
        last_attempt = attempt == MAX_RETRIES - 1
        try:
            response = client.post(url, **kwargs)
        except (httpx.TimeoutException, httpx.TransportError):
            if last_attempt:
                raise
        else:
            if last_attempt or response.status_code not in RETRYABLE_STATUS_CODES:
                return response
        time.sleep(RETRY_BACKOFF_SECONDS * (2**attempt))
    return response


def vision_parse_page(image: "Image.Image") -> PageResult:
    """Send one page image to the configured GLM model and parse its reply.

    Kept as a module-level seam so tests can monkeypatch it.
    """
    buffer = io.BytesIO()
    # JPEG instead of PNG: much smaller payload for scanned/photo-like page
    # content, which speeds up upload and model inference with little
    # visible quality loss at this quality level.
    image.save(buffer, format="JPEG", quality=85)
    encoded = base64.b64encode(buffer.getvalue()).decode()

    response = _post_with_retry(
        _get_vision_client(),
        f"{BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {require_api_key()}"},
        json={
            "model": VISION_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": VISION_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                        },
                    ],
                }
            ],
        },
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    # strict=False: GLM sometimes emits literal unescaped control characters
    # (e.g. raw newlines) inside JSON string values, which json.loads rejects
    # by default with a confusing "invalid control character" error.
    data = json.loads(content, strict=False)
    figures = [
        FigureRegion(bbox=tuple(figure["bbox"]), caption=figure.get("caption", ""))
        for figure in data.get("figures", [])
    ]
    return PageResult(markdown=data["markdown"], figures=figures)


FIGURE_CAPTION_PROMPT = (
    "You are given one figure or table cropped from an academic paper. "
    "Return ONLY a JSON object (no markdown code fences, no commentary) with "
    "exactly one key \"caption\": the figure or table's caption text (e.g. "
    "\"Figure 1: ...\"), or an empty string if none is visible."
)

# Mime type for the data URL — pymupdf's extracted `ext` is usually already
# a valid image subtype ("png", "jpeg"), "jpg" is the one common exception.
_CAPTION_MIME_BY_EXT = {"jpg": "jpeg"}


def caption_figure_image(image_bytes: bytes, ext: str) -> str:
    """Send a single cropped figure/table — not the whole page — to vision
    for just its caption. Far cheaper than a full-page vision call, since the
    body text for pages like this already comes from direct extraction."""
    mime = _CAPTION_MIME_BY_EXT.get(ext.lower(), ext.lower())
    encoded = base64.b64encode(image_bytes).decode()

    response = _post_with_retry(
        _get_vision_client(),
        f"{BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {require_api_key()}"},
        json={
            "model": VISION_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": FIGURE_CAPTION_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/{mime};base64,{encoded}"},
                        },
                    ],
                }
            ],
        },
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    data = json.loads(content, strict=False)
    return data.get("caption", "")


def parse_pdf_file(
    file_path: str,
    figures_dir: str | None = None,
    on_page_done: Callable[[int, int], None] | None = None,
) -> ParsedDocument:
    """`on_page_done`, if given, is called as `(pages_done, total_pages)` —
    a running count of completed pages, not a specific page index. Work
    items run concurrently, so completion order isn't page order.

    Direct text extraction is tried first for every page and used as-is for
    the page's markdown. A page only pays for a *full-page* vision call when
    `_needs_vision` flags it (near-empty text or a high math symbol density).
    Embedded images on an otherwise-fine text page don't trigger that — each
    is captioned individually via the much cheaper `caption_figure_image`
    instead of re-deriving the whole page through vision.
    """
    page_info = extract_page_info(file_path)
    total_pages = len(page_info)
    full_vision_needed = [_needs_vision(info.text) for info in page_info]
    # Rendering is local/cheap (no API call), so render every page whenever
    # at least one needs full-page vision rather than threading page indices
    # through render_pages — the cost this skips is the vision API call.
    pages = render_pages(file_path) if any(full_vision_needed) else [None] * total_pages
    out = Path(figures_dir) if figures_dir else None
    if out:
        out.mkdir(parents=True, exist_ok=True)

    page_markdown: list[str] = [
        "" if full_vision_needed[i] else page_info[i].text for i in range(total_pages)
    ]
    page_figure_blocks: list[list[str]] = [[] for _ in range(total_pages)]
    page_figures: list[list[Figure]] = [[] for _ in range(total_pages)]

    progress_lock = threading.Lock()
    pending_images_by_page = {
        i: len(page_info[i].images)
        for i in range(total_pages)
        if not full_vision_needed[i] and page_info[i].images
    }
    pages_done = sum(
        1
        for i in range(total_pages)
        if not full_vision_needed[i] and not page_info[i].images
    )
    if on_page_done and pages_done:
        on_page_done(pages_done, total_pages)

    def mark_page_done() -> None:
        nonlocal pages_done
        if on_page_done:
            with progress_lock:
                pages_done += 1
                done = pages_done
            on_page_done(done, total_pages)

    def process_full_page_vision(index: int) -> None:
        result = vision_parse_page(pages[index])
        figure_blocks = []
        figures = []
        for fig_index, region in enumerate(result.figures):
            name = f"page{index}_fig{fig_index}.png"
            if out:
                box = tuple(int(v) for v in region.bbox)
                pages[index].crop(box).save(str(out / name))
            figure_blocks.append(f"![{name}]({name})\n\n{region.caption}".strip())
            figures.append(Figure(name=name, caption=region.caption))
        with progress_lock:
            page_markdown[index] = result.markdown
            page_figure_blocks[index] = figure_blocks
            page_figures[index] = figures
        mark_page_done()

    def caption_one_image(page_index: int, image_index: int, image_bytes: bytes, ext: str) -> None:
        caption = caption_figure_image(image_bytes, ext)
        safe_ext = ext if ext.isalnum() else "png"
        name = f"page{page_index}_fig{image_index}.{safe_ext}"
        if out:
            (out / name).write_bytes(image_bytes)
        page_done = False
        with progress_lock:
            page_figure_blocks[page_index].append(f"![{name}]({name})\n\n{caption}".strip())
            page_figures[page_index].append(Figure(name=name, caption=caption))
            pending_images_by_page[page_index] -= 1
            page_done = pending_images_by_page[page_index] == 0
        if page_done:
            mark_page_done()

    tasks: list[Callable[[], None]] = []
    for i in range(total_pages):
        if full_vision_needed[i]:
            tasks.append(lambda i=i: process_full_page_vision(i))
        elif page_info[i].images:
            for img_index, (image_bytes, ext) in enumerate(page_info[i].images):
                tasks.append(
                    lambda i=i, img_index=img_index, image_bytes=image_bytes, ext=ext: (
                        caption_one_image(i, img_index, image_bytes, ext)
                    )
                )

    with ThreadPoolExecutor(max_workers=max(1, min(VISION_CONCURRENCY, max(len(tasks), 1)))) as pool:
        futures = [pool.submit(task) for task in tasks]
        for future in futures:
            future.result()  # re-raise on first failure once all have finished

    markdown_blocks: list[str] = []
    figures: list[Figure] = []
    for page_index in range(total_pages):
        markdown_blocks.append(page_markdown[page_index])
        markdown_blocks.extend(page_figure_blocks[page_index])
        figures.extend(page_figures[page_index])
    return ParsedDocument(
        markdown="\n\n".join(block for block in markdown_blocks if block), figures=figures
    )


def parse_text_file(file_path: str) -> ParsedDocument:
    with Path(file_path).open("r", encoding="utf-8") as file:
        return ParsedDocument(markdown=file.read())


def parse_file(
    file_path: str,
    figures_dir: str | None = None,
    on_page_done: Callable[[int, int], None] | None = None,
) -> ParsedDocument:
    if file_path.lower().endswith(".pdf"):
        return parse_pdf_file(file_path, figures_dir, on_page_done)
    return parse_text_file(file_path)
