"""Extract profile photos embedded in resume PDFs."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None  # type: ignore[assignment,misc]

MIN_PHOTO_BYTES = 2_000
MIN_PHOTO_DIMENSION = 80


def extract_resume_photo(pdf_source: bytes | Path) -> tuple[bytes, str] | None:
    """Return (image_bytes, content_type) for the largest embedded photo, or None."""
    if fitz is None:
        return None

    if isinstance(pdf_source, Path):
        doc = fitz.open(pdf_source)
    else:
        doc = fitz.open(stream=pdf_source, filetype="pdf")

    try:
        best: tuple[int, bytes, str] | None = None
        for page in doc:
            for img in page.get_images(full=True):
                xref = img[0]
                extracted = doc.extract_image(xref)
                width = extracted.get("width", 0)
                height = extracted.get("height", 0)
                data = extracted.get("image", b"")
                if width < MIN_PHOTO_DIMENSION or height < MIN_PHOTO_DIMENSION:
                    continue
                if len(data) < MIN_PHOTO_BYTES:
                    continue
                ext = extracted.get("ext", "jpeg")
                content_type = {
                    "jpeg": "image/jpeg",
                    "jpg": "image/jpeg",
                    "png": "image/png",
                    "webp": "image/webp",
                }.get(ext.lower(), "image/jpeg")
                area = width * height
                if best is None or area > best[0]:
                    best = (area, data, content_type)
        if best is None:
            return None
        return best[1], best[2]
    finally:
        doc.close()


def extract_resume_photo_from_bytes(pdf_bytes: bytes) -> tuple[bytes, str] | None:
    return extract_resume_photo(pdf_bytes)
