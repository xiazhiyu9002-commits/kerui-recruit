from pathlib import Path

import pymupdf
from docx import Document

from kerui_recruit.resumes.extract import extract_contact, extract_text


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


def test_extract_contact_finds_email_and_mainland_mobile() -> None:
    """Sensitive contact details must be discoverable for encrypted persistence."""
    contact = extract_contact(
        "张三\n邮箱: zhang.san@example.com\n手机: 13800138000\n电话: 010-12345678"
    )

    assert contact.email == "zhang.san@example.com"
    assert contact.phone == "13800138000"


def test_extract_contact_returns_none_when_absent() -> None:
    """A resume without contact details must yield no false positives."""
    contact = extract_contact("张三 本科 6年 Java Python")

    assert contact.email is None
    assert contact.phone is None
