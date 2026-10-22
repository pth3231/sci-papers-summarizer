from pathlib import Path

import pytest

from src.services import parser


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
