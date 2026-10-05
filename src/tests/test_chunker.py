from src.services.chunker import SENTENCE_SPLIT_RE, chunk_markdown

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

def test_oversized_figure_caption_respects_max_size():
    caption = ("Figure 1 shows a training curve detail here. " * 28).strip()  # ~1250 chars
    md = f"# Results\n\n![Figure 1](figs/fig1.png)\n\n{caption}\n"
    chunks = chunk_markdown(md, "d")
    assert all(len(c.text) <= 900 for c in chunks)
    figs = [c for c in chunks if c.kind == "figure"]
    assert len(figs) == 1
    assert "![Figure 1](figs/fig1.png)" in figs[0].text
    assert figs[0].figure_path == "figs/fig1.png"
    # caption overflow becomes plain text chunks in the same section
    overflow = [c for c in chunks if c.kind == "text" and "training curve" in c.text]
    assert overflow and all(c.section == "Results" for c in overflow)
    # no content lost across the pieces
    sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(caption)]
    joined = "\n\n".join(c.text for c in chunks)
    assert all(s in joined for s in sentences)

def test_chunk_ids_and_indices():
    chunks = build()
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert all(c.chunk_id == f"d1_chunk_{c.chunk_index}" for c in chunks)

def test_plain_text_passthrough():
    chunks = chunk_markdown("just text\n\nmore text\n", "d9")
    assert all(c.section == "" and c.kind == "text" for c in chunks)
