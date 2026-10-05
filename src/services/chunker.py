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
            section_path = section_path[: max(level - 2, 0)]
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
        if figure_path is not None:
            # Figures stand alone so the caption chunk is never merged into prose.
            flush()
            buffer.append((text, figure_path))
            flush()
            continue
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
                    buffer.append((piece, None))
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
