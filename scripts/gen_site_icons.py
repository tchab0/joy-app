#!/usr/bin/env python3
"""Génère favicon + icônes PWA à partir de data/logo-joy.webp."""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]  # workspace root
SRC = ROOT / "data" / "logo-joy.webp"
OUT = Path(__file__).resolve().parents[1] / "users" / "static" / "users" / "icons"


def square_resize(im: Image.Image, size: int) -> Image.Image:
    resized = im.copy()
    resized.thumbnail((size, size), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    x = (size - resized.width) // 2
    y = (size - resized.height) // 2
    canvas.paste(resized, (x, y), resized)
    return canvas


def main() -> None:
    if not SRC.is_file():
        raise SystemExit(f"Logo introuvable: {SRC}")
    OUT.mkdir(parents=True, exist_ok=True)
    im = Image.open(SRC)
    if im.mode != "RGBA":
        im = im.convert("RGBA")

    # garder l’original (qualité) pour og:image legacy
    (OUT / "logo-joy.webp").write_bytes(SRC.read_bytes())

    # OG / Twitter 1200×630 (JPG)
    og_src = ROOT / "data" / "Joy-Cyel.jpg"
    if not og_src.is_file():
        og_src = SRC
    og = Image.open(og_src).convert("RGB")
    target_w, target_h = 1200, 630
    src_ratio = og.width / og.height
    tgt_ratio = target_w / target_h
    if src_ratio > tgt_ratio:
        new_h = target_h
        new_w = int(new_h * src_ratio)
    else:
        new_w = target_w
        new_h = int(new_w / src_ratio)
    og = og.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    og.crop((left, top, left + target_w, top + target_h)).save(
        OUT / "og-image.jpg", "JPEG", quality=85, optimize=True
    )

    for size in (180, 192, 512):
        square_resize(im, size).save(OUT / f"icon-{size}.png", "PNG")

    fav32 = square_resize(im, 32)
    fav32.save(OUT / "favicon-32.png", "PNG")
    fav32.save(OUT / "favicon.ico", format="ICO", sizes=[(32, 32)])

    print("OK ->", OUT)
    for p in sorted(OUT.iterdir()):
        print(f"  {p.name:20} {p.stat().st_size:6} B")


if __name__ == "__main__":
    main()
