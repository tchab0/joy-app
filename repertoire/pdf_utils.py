"""Helpers PDF : fusion d’images et extraction de plages de pages."""

from __future__ import annotations

import io
from pathlib import Path

from django.core.files.base import ContentFile


def images_to_pdf_bytes(image_paths: list[str | Path]) -> bytes:
    """Fusionne des images (JPG/PNG) en un seul PDF."""
    from PIL import Image

    if not image_paths:
        raise ValueError("Aucune image à convertir.")

    pages: list[Image.Image] = []
    for path in image_paths:
        img = Image.open(path)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")
        pages.append(img)

    buf = io.BytesIO()
    first, rest = pages[0], pages[1:]
    first.save(buf, format="PDF", save_all=True, append_images=rest)
    for img in pages:
        img.close()
    return buf.getvalue()


def extract_pdf_pages_bytes(source_path: str | Path, start: int, end: int) -> bytes:
    """
    Extrait les pages [start, end] (1-indexées, inclusives) d’un PDF.
    """
    import pikepdf

    if start < 1 or end < start:
        raise ValueError("Plage de pages invalide.")

    with pikepdf.open(source_path) as src:
        n = len(src.pages)
        if end > n:
            raise ValueError(f"Le PDF n’a que {n} page(s).")
        dst = pikepdf.Pdf.new()
        for i in range(start - 1, end):
            dst.pages.append(src.pages[i])
        buf = io.BytesIO()
        dst.save(buf)
        return buf.getvalue()


def pdf_page_count(source_path: str | Path) -> int:
    import pikepdf

    with pikepdf.open(source_path) as pdf:
        return len(pdf.pages)


def content_file_from_bytes(data: bytes, filename: str) -> ContentFile:
    return ContentFile(data, name=filename)
