from pathlib import Path


def parse_text_file(file_path: str) -> str:
    path = Path(file_path)

    with path.open("r", encoding="utf-8") as file:
        text = file.read()

    return text


def parse_pdf_file(file_path: str) -> str:
    from pypdf import PdfReader

    reader = PdfReader(file_path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def parse_file(file_path: str) -> str:
    if file_path.lower().endswith(".pdf"):
        return parse_pdf_file(file_path)
    return parse_text_file(file_path)
