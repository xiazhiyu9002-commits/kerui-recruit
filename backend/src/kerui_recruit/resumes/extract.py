from __future__ import annotations

import importlib
import platform
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from docx import Document

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")


class LegacyDocConversionError(RuntimeError):
    code = "E_DOC_CONVERTER_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class ExtractedContact:
    email: str | None
    phone: str | None


def extract_contact(text: str) -> ExtractedContact:
    """Extract a best-effort email and mainland mobile number from raw text."""
    email_match = _EMAIL_RE.search(text)
    phone_match = _PHONE_RE.search(text)
    return ExtractedContact(
        email=email_match.group(0) if email_match else None,
        phone=phone_match.group(0) if phone_match else None,
    )


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
    if suffix == ".doc":
        text = _normalize_text(_extract_legacy_doc(path))
        if not text:
            raise LegacyDocConversionError(
                "旧版 DOC 未提取到文字，请将文件另存为 DOCX 后重试"
            )
        return ExtractedText(text=text, page_count=1, requires_ocr=False)
    raise ValueError(f"Text extraction is unsupported for {suffix or 'unknown'}")


def _extract_legacy_doc(path: Path) -> str:
    system = platform.system()
    if system == "Windows":
        return _extract_doc_with_word(path)
    if system == "Darwin":
        return _extract_doc_with_textutil(path)
    raise LegacyDocConversionError(
        "当前系统不支持旧版 DOC，请将文件另存为 DOCX 后重试"
    )


def _extract_doc_with_word(path: Path) -> str:
    try:
        pythoncom = importlib.import_module("pythoncom")
        win32_client = importlib.import_module("win32com.client")
    except ModuleNotFoundError as error:
        raise LegacyDocConversionError(
            "Windows 解析旧版 DOC 需要 Microsoft Word，请安装 Word 或另存为 DOCX 后重试"
        ) from error

    word = None
    document = None
    com_initialized = False
    try:
        pythoncom.CoInitialize()
        com_initialized = True
        word = win32_client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        document = word.Documents.Open(
            str(path.resolve()),
            ConfirmConversions=False,
            ReadOnly=True,
            AddToRecentFiles=False,
        )
        return str(document.Content.Text)
    except Exception as error:
        raise LegacyDocConversionError(
            "Microsoft Word 无法读取旧版 DOC，请将文件另存为 DOCX 后重试"
        ) from error
    finally:
        if document is not None:
            try:
                document.Close(SaveChanges=0)
            except Exception:
                pass
        if word is not None:
            try:
                word.Quit()
            except Exception:
                pass
        if com_initialized:
            pythoncom.CoUninitialize()


def _extract_doc_with_textutil(path: Path) -> str:
    try:
        result = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", str(path.resolve())],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        raise LegacyDocConversionError(
            "macOS textutil 无法使用，请将旧版 DOC 另存为 DOCX 后重试"
        ) from error
    if result.returncode != 0:
        raise LegacyDocConversionError(
            "macOS textutil 无法读取旧版 DOC，请将文件另存为 DOCX 后重试"
        )
    return result.stdout


def _normalize_text(text: str) -> str:
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())
