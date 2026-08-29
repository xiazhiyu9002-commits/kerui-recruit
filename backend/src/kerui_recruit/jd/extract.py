from __future__ import annotations

from io import BytesIO

from docx import Document
from openpyxl import load_workbook


class UnsupportedJdType(ValueError):
    code = "E_JD_FILE_TYPE_UNSUPPORTED"


def extract_jd_text(filename: str, content: bytes) -> str:
    """Extract plain text from a Word or Excel JD file."""
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix == "docx":
        document = Document(BytesIO(content))
        paragraphs = [paragraph.text for paragraph in document.paragraphs]
        for table in document.tables:
            paragraphs.extend(cell.text for row in table.rows for cell in row.cells)
        return _normalize("\n".join(paragraphs))
    if suffix == "xlsx":
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
        rows: list[str] = []
        for sheet in workbook.worksheets:
            for row in sheet.iter_rows(values_only=True):
                rows.append(" ".join(str(cell) for cell in row if cell is not None))
        return _normalize("\n".join(rows))
    raise UnsupportedJdType(f"Unsupported JD type: {suffix or 'none'}")


def _normalize(text: str) -> str:
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())
