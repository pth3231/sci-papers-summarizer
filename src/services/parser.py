import base64
import io
import json
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from src.services.generator import BASE_URL, MODEL, require_api_key


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


def render_pages(pdf_path: str, dpi: int = 150) -> list["Image.Image"]:
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


def close_vision_client() -> None:
    global _vision_client
    if _vision_client is not None:
        _vision_client.close()
        _vision_client = None


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
            markdown_blocks.append(f"![{name}]({name})\n\n{region.caption}".strip())
            figures.append(Figure(name=name, caption=region.caption))
    return ParsedDocument(markdown="\n\n".join(markdown_blocks), figures=figures)


def parse_text_file(file_path: str) -> ParsedDocument:
    with Path(file_path).open("r", encoding="utf-8") as file:
        return ParsedDocument(markdown=file.read())


def parse_file(file_path: str, figures_dir: str | None = None) -> ParsedDocument:
    if file_path.lower().endswith(".pdf"):
        return parse_pdf_file(file_path, figures_dir)
    return parse_text_file(file_path)
