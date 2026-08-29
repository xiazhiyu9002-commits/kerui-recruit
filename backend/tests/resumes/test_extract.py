from pathlib import Path

import pymupdf
from docx import Document

from kerui_recruit.resumes.extract import extract_text


def test_pdf_and_docx_extract_visible_text(tmp_path: Path) -> None:
    """A readable office document must not be sent through costly OCR."""
    pdf_path = tmp_path / "resume.pdf"
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "Python Finance Resume")
    pdf.save(pdf_path)
    pdf.close()
    docx_path = tmp_path / "resume.docx"
    docx = Document()
    docx.add_paragraph("Python Finance Resume")
    docx.save(docx_path)

    pdf_result = extract_text(pdf_path)
    docx_result = extract_text(docx_path)

    assert "Python Finance" in pdf_result.text
    assert "Python Finance" in docx_result.text
    assert pdf_result.requires_ocr is False
    assert docx_result.requires_ocr is False


def test_blank_pdf_requires_ocr(tmp_path: Path) -> None:
    """A scan with no text layer must never be marked as successfully extracted."""
    pdf_path = tmp_path / "scan.pdf"
    pdf = pymupdf.open()
    pdf.new_page()
    pdf.save(pdf_path)
    pdf.close()

    result = extract_text(pdf_path)

    assert result.text == ""
    assert result.requires_ocr is True
    assert result.page_count == 1
