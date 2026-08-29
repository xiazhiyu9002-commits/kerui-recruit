from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf
from docx import Document


@dataclass(frozen=True, slots=True)
class ExtractedText:
    text: str
    page_count: int
    requires_ocr: bool


def extract_text(path: Path) -> ExtractedText:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        with pymupdf.open(path) as document:
            pages = [page.get_text("text") for page in document]
            text = _normalize_text("\n".join(pages))
            return ExtractedText(
                text=text,
                page_count=document.page_count,
                requires_ocr=len(text) < 20,
            )
    if suffix == ".docx":
        document = Document(path)
        paragraphs = [paragraph.text for paragraph in document.paragraphs]
        for table in document.tables:
            paragraphs.extend(cell.text for row in table.rows for cell in row.cells)
        return ExtractedText(
            text=_normalize_text("\n".join(paragraphs)),
            page_count=1,
            requires_ocr=False,
        )
    raise ValueError(f"Text extraction is unsupported for {suffix or 'unknown'}")


def _normalize_text(text: str) -> str:
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())
