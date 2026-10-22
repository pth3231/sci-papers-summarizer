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

    monkeypatch.setattr(
        parser, "extract_page_info", lambda pdf_path: [parser.PageInfo(text="")]
    )
    monkeypatch.setattr(parser, "render_pages", fake_render_pages)
    monkeypatch.setattr(parser, "vision_parse_page", fake_vision_parse_page)
    doc = parser.parse_file("whatever.pdf", figures_dir=str(fig_dir))
    assert doc.markdown.startswith("# T")
    assert [f.name for f in doc.figures] == ["page0_fig0.png"]
    assert (fig_dir / "page0_fig0.png").exists()


def test_pdf_multi_page_figures_with_bracketed_caption(tmp_path: Path, monkeypatch):
    fig_dir = tmp_path / "figures"

    class FakeImage:
        def crop(self, box):
            return self

        def save(self, path):
            Path(path).write_bytes(b"png")

    fake_pages = [FakeImage(), FakeImage()]

    def fake_render_pages(pdf_path):
        return fake_pages

    def fake_vision_parse_page(image):
        index = fake_pages.index(image)
        if index == 0:
            return parser.PageResult(
                markdown="# Page 1",
                figures=[
                    parser.FigureRegion(
                        bbox=(0, 0, 1, 1), caption="Figure 1: accuracy [12]"
                    )
                ],
            )
        return parser.PageResult(
            markdown="# Page 2",
            figures=[
                parser.FigureRegion(bbox=(0, 0, 1, 1), caption="Figure 2: loss curve")
            ],
        )

    monkeypatch.setattr(
        parser,
        "extract_page_info",
        lambda pdf_path: [parser.PageInfo(text=""), parser.PageInfo(text="")],
    )
    monkeypatch.setattr(parser, "render_pages", fake_render_pages)
    monkeypatch.setattr(parser, "vision_parse_page", fake_vision_parse_page)
    doc = parser.parse_file("whatever.pdf", figures_dir=str(fig_dir))

    assert [f.name for f in doc.figures] == ["page0_fig0.png", "page1_fig0.png"]
    assert (fig_dir / "page0_fig0.png").exists()
    assert (fig_dir / "page1_fig0.png").exists()
    assert "![page0_fig0.png](page0_fig0.png)" in doc.markdown


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


def test_post_with_retry_succeeds_without_retrying_on_first_try(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200

    class FakeClient:
        def post(self, *args, **kwargs):
            calls.append(1)
            return FakeResponse()

    monkeypatch.setattr(parser, "MAX_RETRIES", 3)
    sleeps = []
    monkeypatch.setattr(parser.time, "sleep", lambda s: sleeps.append(s))

    response = parser._post_with_retry(FakeClient(), "http://x")
    assert response.status_code == 200
    assert len(calls) == 1
    assert sleeps == []


def test_post_with_retry_retries_on_429_then_succeeds(monkeypatch):
    responses = iter([429, 200])

    class FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code

    class FakeClient:
        def post(self, *args, **kwargs):
            return FakeResponse(next(responses))

    monkeypatch.setattr(parser, "MAX_RETRIES", 3)
    sleeps = []
    monkeypatch.setattr(parser.time, "sleep", lambda s: sleeps.append(s))

    response = parser._post_with_retry(FakeClient(), "http://x")
    assert response.status_code == 200
    assert len(sleeps) == 1  # retried exactly once


def test_post_with_retry_does_not_retry_on_400(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 400

    class FakeClient:
        def post(self, *args, **kwargs):
            calls.append(1)
            return FakeResponse()

    monkeypatch.setattr(parser, "MAX_RETRIES", 3)
    sleeps = []
    monkeypatch.setattr(parser.time, "sleep", lambda s: sleeps.append(s))

    response = parser._post_with_retry(FakeClient(), "http://x")
    assert response.status_code == 400
    assert len(calls) == 1  # deterministic client error — no point retrying
    assert sleeps == []


def test_post_with_retry_gives_up_after_exhausting_retries_on_persistent_500(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 500

    class FakeClient:
        def post(self, *args, **kwargs):
            calls.append(1)
            return FakeResponse()

    monkeypatch.setattr(parser, "MAX_RETRIES", 3)
    monkeypatch.setattr(parser.time, "sleep", lambda s: None)

    response = parser._post_with_retry(FakeClient(), "http://x")
    assert response.status_code == 500  # caller's raise_for_status() will raise this
    assert len(calls) == 3


def test_post_with_retry_retries_on_timeout_then_succeeds(monkeypatch):
    import httpx

    class FakeResponse:
        status_code = 200

    attempts = {"count": 0}

    class FakeClient:
        def post(self, *args, **kwargs):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise httpx.ConnectTimeout("timed out")
            return FakeResponse()

    monkeypatch.setattr(parser, "MAX_RETRIES", 3)
    sleeps = []
    monkeypatch.setattr(parser.time, "sleep", lambda s: sleeps.append(s))

    response = parser._post_with_retry(FakeClient(), "http://x")
    assert response.status_code == 200
    assert attempts["count"] == 2
    assert len(sleeps) == 1


def test_vision_parse_page_parses_markdown_and_figures(monkeypatch):
    import json as json_module
    from PIL import Image

    class FakeResponse:
        status_code = 200

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


def test_vision_parse_page_tolerates_unescaped_control_characters(monkeypatch):
    from PIL import Image

    # GLM sometimes emits a literal raw newline inside a JSON string value
    # instead of escaping it as \n — strict JSON parsing rejects that.
    raw_content = '{"markdown": "line one\nline two", "figures": []}'

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": raw_content}}]}

    class FakeClient:
        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(parser, "_get_vision_client", lambda: FakeClient())
    monkeypatch.setattr(parser, "require_api_key", lambda: "test-key")
    result = parser.vision_parse_page(Image.new("RGB", (10, 10)))
    assert result.markdown == "line one\nline two"


def test_caption_figure_image_parses_caption(monkeypatch):
    import json as json_module

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {"message": {"content": json_module.dumps({"caption": "Figure 2: loss"})}}
                ]
            }

    class FakeClient:
        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(parser, "_get_vision_client", lambda: FakeClient())
    monkeypatch.setattr(parser, "require_api_key", lambda: "test-key")
    caption = parser.caption_figure_image(b"somebytes", "png")
    assert caption == "Figure 2: loss"


def test_needs_vision_true_when_text_is_near_empty():
    assert parser._needs_vision("  ")


def test_needs_vision_true_when_math_density_is_high():
    text = "∀x ∈ ℝ: ∑ⁱ αᵢ ≈ ∂f/∂x ± √2 ≤ ∫ g(x)dx"
    assert parser._needs_vision(text)


def test_needs_vision_false_for_plain_prose():
    text = "This paper presents a method for summarizing scientific text. " * 3
    assert not parser._needs_vision(text)


def test_needs_vision_false_for_plain_text_page_with_images():
    # Embedded images alone no longer force a full-page vision call — see
    # caption_figure_image, which handles figures without re-deriving the
    # whole page's text through vision.
    assert not parser._needs_vision("This page has plenty of ordinary body text.")


def test_parse_pdf_file_skips_vision_for_plain_text_pages(tmp_path, monkeypatch):
    calls = []

    def fake_vision_parse_page(image):
        calls.append(image)
        return parser.PageResult(markdown="# Scanned page")

    monkeypatch.setattr(
        parser,
        "extract_page_info",
        lambda pdf_path: [
            parser.PageInfo(text="Plain prose body text, nothing special here."),
            parser.PageInfo(text=""),
        ],
    )
    monkeypatch.setattr(parser, "render_pages", lambda pdf_path: ["img0", "img1"])
    monkeypatch.setattr(parser, "vision_parse_page", fake_vision_parse_page)

    doc = parser.parse_file(str(tmp_path / "whatever.pdf"))
    assert len(calls) == 1  # only the near-empty (scanned) page hit the vision model
    assert "Plain prose body text" in doc.markdown
    assert "# Scanned page" in doc.markdown


def test_parse_pdf_file_captions_embedded_images_without_full_page_vision(tmp_path, monkeypatch):
    full_page_calls = []
    caption_calls = []

    def fake_vision_parse_page(image):
        full_page_calls.append(image)
        return parser.PageResult(markdown="# should not be used")

    def fake_caption_figure_image(image_bytes, ext):
        caption_calls.append((image_bytes, ext))
        return "Figure 1: a plot"

    monkeypatch.setattr(
        parser,
        "extract_page_info",
        lambda pdf_path: [
            parser.PageInfo(
                text="Plain prose body text, nothing special here.",
                images=[(b"rawbytes", "jpeg")],
            )
        ],
    )
    monkeypatch.setattr(parser, "vision_parse_page", fake_vision_parse_page)
    monkeypatch.setattr(parser, "caption_figure_image", fake_caption_figure_image)

    fig_dir = tmp_path / "figures"
    doc = parser.parse_file(str(tmp_path / "whatever.pdf"), figures_dir=str(fig_dir))

    assert full_page_calls == []  # text was fine — no full-page vision call
    assert caption_calls == [(b"rawbytes", "jpeg")]
    assert "Plain prose body text" in doc.markdown
    assert "Figure 1: a plot" in doc.markdown
    assert [f.name for f in doc.figures] == ["page0_fig0.jpeg"]
    assert (fig_dir / "page0_fig0.jpeg").read_bytes() == b"rawbytes"
