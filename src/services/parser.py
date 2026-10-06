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
