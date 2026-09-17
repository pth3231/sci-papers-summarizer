from dataclasses import dataclass

@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    text: str
    chunk_index: int

def chunk_text(text: str, document_id:str, chunk_size: int = 1000, overlap: int = 200,) -> list[Chunk]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")

    if overlap < 0:
        raise ValueError("overlap cannot be negative")

    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    chunks = []
    start = 0
    chunk_index = 0

    while start < len(text):
        end = start + chunk_size

        chunk = Chunk(chunk_id=f"{document_id}_chunk_{chunk_index}", document_id=document_id, text=text[start:end], chunk_index=chunk_index)
        chunks.append(chunk)

        start += chunk_size - overlap
        chunk_index += 1

    return chunks
