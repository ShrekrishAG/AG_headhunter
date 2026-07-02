"""Extract text from resume PDFs."""

from __future__ import annotations

from pathlib import Path


def extract_pdf_text(path: Path) -> str:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return _pdftotext_cli(path)

    try:
        doc = fitz.open(str(path))
        parts = [page.get_text() for page in doc]
        doc.close()
        return "\n".join(parts)
    except Exception:
        return _pdftotext_cli(path)


def _pdftotext_cli(path: Path) -> str:
    import subprocess

    try:
        return subprocess.check_output(
            ["pdftotext", str(path), "-"],
            text=True,
            errors="replace",
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""
