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
    monkeypatch.setattr(parser, "require_api_key", lambda: "test-key")
    image = Image.new("RGB", (100, 100))
    result = parser.vision_parse_page(image)
    assert result.markdown == "# Intro\n\ntext"
    assert result.figures == [parser.FigureRegion(bbox=(0, 0, 10, 10), caption="Figure 1: a plot")]
