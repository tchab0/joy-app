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


def render_pdf_page_jpeg(
    source_path: str | Path,
    page: int,
    *,
    max_width: int = 720,
    quality: int = 72,
) -> bytes:
    """
    Rasterise la page `page` (1-indexée) en JPEG.
    `max_width` borne la largeur pour les miniatures / aperçu.
    """
    import fitz

    if page < 1:
        raise ValueError("Numéro de page invalide.")
    if max_width < 64:
        max_width = 64

    doc = fitz.open(source_path)
    try:
        if page > doc.page_count:
            raise ValueError(f"Le PDF n’a que {doc.page_count} page(s).")
        pg = doc.load_page(page - 1)
        rect = pg.rect
        scale = max_width / float(rect.width) if rect.width else 1.0
        if scale > 2.0:
            scale = 2.0
        pix = pg.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        # PyMuPDF: quality via output params when available
        try:
            return pix.tobytes("jpeg", jpg_quality=quality)
        except TypeError:
            return pix.tobytes("jpeg")
    finally:
        doc.close()


def content_file_from_bytes(data: bytes, filename: str) -> ContentFile:
    return ContentFile(data, name=filename)
