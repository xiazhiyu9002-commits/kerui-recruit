from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest
from docx import Document

from kerui_recruit.resumes import extract as extract_module
from kerui_recruit.resumes.extract import (
    LegacyDocConversionError,
    extract_contact,
    extract_text,
)


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


def test_legacy_doc_extraction_preserves_the_source_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "legacy.doc"
    original = b"legacy-binary-content"
    source.write_bytes(original)
    monkeypatch.setattr(
        extract_module,
        "_extract_legacy_doc",
        lambda _path: "Python Finance Resume",
    )

    result = extract_text(source)

    assert result.text == "Python Finance Resume"
    assert result.requires_ocr is False
    assert source.read_bytes() == original


def test_windows_legacy_doc_requires_microsoft_word(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "legacy.doc"
    source.write_bytes(b"legacy")
    monkeypatch.setattr(extract_module.platform, "system", lambda: "Windows")

    def missing_module(_name: str):
        raise ModuleNotFoundError

    monkeypatch.setattr(extract_module.importlib, "import_module", missing_module)

    with pytest.raises(LegacyDocConversionError, match="Microsoft Word.*DOCX"):
        extract_module._extract_legacy_doc(source)


def test_macos_legacy_doc_uses_system_textutil(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "legacy.doc"
    source.write_bytes(b"legacy")
    captured: list[str] = []

    def fake_run(command: list[str], **_kwargs):
        captured.extend(command)
        return SimpleNamespace(returncode=0, stdout="Python Resume", stderr="")

    monkeypatch.setattr(extract_module.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(extract_module.subprocess, "run", fake_run)

    assert extract_module._extract_legacy_doc(source) == "Python Resume"
    assert captured == ["textutil", "-convert", "txt", "-stdout", str(source.resolve())]


def test_windows_word_converter_initializes_com_and_never_saves(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "legacy.doc"
    source.write_bytes(b"legacy")
    calls: list[object] = []

    class FakeDocument:
        Content = SimpleNamespace(Text="Python Resume")

        def Close(self, *, SaveChanges: int) -> None:
            calls.append(("close", SaveChanges))

    class FakeWord:
        Documents = SimpleNamespace(Open=lambda *_args, **_kwargs: FakeDocument())
        Visible = True
        DisplayAlerts = 1

        def Quit(self) -> None:
            calls.append("quit")

    fake_pythoncom = SimpleNamespace(
        CoInitialize=lambda: calls.append("initialize"),
        CoUninitialize=lambda: calls.append("uninitialize"),
    )
    fake_client = SimpleNamespace(DispatchEx=lambda _name: FakeWord())

    def fake_import(name: str):
        return fake_pythoncom if name == "pythoncom" else fake_client

    monkeypatch.setattr(extract_module.importlib, "import_module", fake_import)

    assert extract_module._extract_doc_with_word(source) == "Python Resume"
    assert calls == ["initialize", ("close", 0), "quit", "uninitialize"]
