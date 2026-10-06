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
