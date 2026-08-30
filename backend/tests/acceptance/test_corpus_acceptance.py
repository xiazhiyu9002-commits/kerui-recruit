from __future__ import annotations

import json
from pathlib import Path

import pymupdf
from docx import Document

from kerui_recruit.bench.corpus_acceptance import scan_corpus


def _write_pdf(path: Path, text: str | None) -> None:
    document = pymupdf.open()
    page = document.new_page()
    if text:
        page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def _write_docx(path: Path, text: str) -> None:
    document = Document()
    document.add_paragraph(text)
    document.save(path)


def test_scan_corpus_reports_only_aggregate_metrics(tmp_path: Path) -> None:
    source = tmp_path / "private-corpus"
    source.mkdir()
    _write_pdf(source / "candidate-secret.pdf", "Python engineer with six years experience")
    (source / "duplicate-secret.pdf").write_bytes((source / "candidate-secret.pdf").read_bytes())
    _write_pdf(source / "scan-secret.pdf", None)
    _write_docx(source / "resume-secret.docx", "Java engineer with five years experience")
    (source / "photo-secret.png").write_bytes(b"not-a-resume")

    inventory = scan_corpus(source)
    report = inventory.to_dict()
    serialized = json.dumps(report, ensure_ascii=False)

    assert report["total_files"] == 5
    assert report["supported_files"] == 4
    assert report["unsupported_files"] == 1
    assert report["duplicate_files"] == 1
    assert report["extractable_files"] == 3
    assert report["ocr_required_files"] == 1
    assert report["extraction_failed_files"] == 0
    assert report["formats"]["pdf"]["files"] == 3
    assert report["formats"]["docx"]["files"] == 1
    assert len(report["aggregate_sha256"]) == 64
    assert "candidate-secret" not in serialized
    assert "Python engineer" not in serialized
    assert str(source) not in serialized


def test_scan_corpus_is_deterministic_and_does_not_modify_sources(tmp_path: Path) -> None:
    source = tmp_path / "corpus"
    source.mkdir()
    _write_docx(source / "resume.docx", "Data engineer experience")
    before = (source / "resume.docx").read_bytes()

    first = scan_corpus(source).to_dict()
    second = scan_corpus(source).to_dict()

    assert first == second
    assert (source / "resume.docx").read_bytes() == before
