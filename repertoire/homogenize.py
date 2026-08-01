"""Homogénéisation de l’inbox Drive → arborescence morceau/poste.pdf."""

from __future__ import annotations

import json
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from django.utils.text import slugify

from repertoire.pdf_utils import images_to_pdf_bytes

# Extensions traitées / ignorées
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
PDF_EXT = {".pdf"}
SKIP_EXT = {".mp3", ".wav", ".m4a", ".zip", ".docx", ".doc", ".txt", ".DS_Store"}

# Dossiers / fichiers à ignorer (pas des morceaux)
SKIP_NAME_FRAGMENTS = (
    "backing track",
    "liste joy",
    "liste  joy",
    "deroule",
    "set list joy",
    "set-list",
    "bundle.zip",
    "whatsapp image",
)

# Titres canoniques (clé normalisée → titre affiché)
TITLE_ALIASES: dict[str, str] = {
    "alligator boogaloo": "Alligator Boogaloo",
    "alligator  boogaloo": "Alligator Boogaloo",
    "baby its cold outside": "Baby It's Cold Outside",
    "baby its cold ourside": "Baby It's Cold Outside",
    "puttin on the ritz": "Puttin' on the Ritz",
    "sing sing sing": "Sing, Sing, Sing",
    "the lady is a tramp": "The Lady Is a Tramp",
    "the lady is tramp": "The Lady Is a Tramp",
    "frim fram sauce": "The Frim Fram Sauce",
    "the frim fram sauce": "The Frim Fram Sauce",
    "watermelon man": "Watermelon Man",
    "no moon at all": "No Moon at All",
    "love me or leave me": "Love Me or Leave Me",
    "lovemeorleaveme swr 2022": "Love Me or Leave Me",
    "a foggy day": "A Foggy Day",
    "a foggy day shared": "A Foggy Day",
    "fly me to the moon": "Fly Me to the Moon",
    "take the a train": "Take the A Train",
    "take the": "Take the A Train",
    "blue skies": "Blue Skies",
    "blue skies holmes 51 pages": "Blue Skies",
    "copie de blue skies holmes 51 pages": "Blue Skies",
    "cheek to cheek": "Cheek to Cheek",
    "cheek to cheek full big band may frank sinatra": "Cheek to Cheek",
    "cheek to cheek bass": "Cheek to Cheek",
    "alright okay you win": "Alright, Okay, You Win",
    "angel eyes dm": "Angel Eyes",
    "angel eyes": "Angel Eyes",
    "black coffee": "Black Coffee",
    "every day": "Every Day",
    "feeling good": "Feeling Good",
    "fever": "Fever",
    "hay burner nestico": "Hay Burner",
    "i cant give you anything but love": "I Can't Give You Anything but Love",
    "i cant give you anything but love 2": "I Can't Give You Anything but Love",
    "i cant give you bass": "I Can't Give You Anything but Love",
    "i cant give you trombone i": "I Can't Give You Anything but Love",
    "it could happen to you": "It Could Happen to You",
    "itcouldhapentoyou": "It Could Happen to You",
    "it dont mean a thing": "It Don't Mean a Thing",
    "lil darlin": "Li'l Darlin'",
    "my funny valentine": "My Funny Valentine",
    "night and day": "Night and Day",
    "orange colored sky": "Orange Colored Sky",
    "orange colored sky 1": "Orange Colored Sky",
    "orange colored sky 2": "Orange Colored Sky",
    "route 66": "Route 66",
    "somebody loves me": "Somebody Loves Me",
    "somebody loves me 1": "Somebody Loves Me",
    "splanky": "Splanky",
    "splanky full big band nestico": "Splanky",
    "sway": "Sway",
    "the look of love": "The Look of Love",
    "the look of love 2": "The Look of Love",
    "the man i love": "The Man I Love",
    "the man i love arr wolpe pdf free full score": "The Man I Love",
    "anthropology": "Anthropology",
    "bei mir bist du schon means that youre grand": "Bei Mir Bist Du Schön",
    "bei mir bist du schon": "Bei Mir Bist Du Schön",
    "big swing face": "Big Swing Face",
    "but not for me": "But Not for Me",
    "caribbean dance": "Caribbean Dance",
    "carribean dance": "Caribbean Dance",
    "the cool one": "The Cool One",
    "big band vocal fly me to the moon": "Fly Me to the Moon",
    "big band vocal fly me to the moon parts 1": "Fly Me to the Moon",
    "big band vocal fly me to the moon parts 2": "Fly Me to the Moon",
    "big band vocal fly me to the moon scores": "Fly Me to the Moon",
    "big band vocal take the a train": "Take the A Train",
    "big band vocal take the a train parts 1": "Take the A Train",
    "big band vocal take the a train parts 1 1": "Take the A Train",
    "big band vocal take the a train parts 2": "Take the A Train",
    "big band vocal take the a train scores": "Take the A Train",
    "cheek to cheek full big band may frank sinatra 1": "Cheek to Cheek",
    "i cant give you": "I Can't Give You Anything but Love",
    "i cant give you 1": "I Can't Give You Anything but Love",
    "feeling good amy michael buble": "Feeling Good",
    "feeling good amy michael buble piano": "Feeling Good",
    "somebody loves me bass": "Somebody Loves Me",
    "i can t give you 1": "I Can't Give You Anything but Love",
    "i can t give you": "I Can't Give You Anything but Love",
    "bei mir bist du schon means that you re grand": "Bei Mir Bist Du Schön",
    "lovemeorleavemeswr 2022 17": "Love Me or Leave Me",
    "lovemeorleaveme swr 2022 17": "Love Me or Leave Me",
    "night and day solo bass clef part substitute for vocal": "Night and Day",
    "night and day solo bb part substitute for vocal": "Night and Day",
    "night and day solo eb part substitute for vocal": "Night and Day",
    "night and day vocals": "Night and Day",
    "no moon at all a": "No Moon at All",
    "no moon at all b": "No Moon at All",
    "itcould vocal": "It Could Happen to You",
    "it could happen to you": "It Could Happen to You",
}


def normalize_key(text: str) -> str:
    t = text.lower().replace("’", "'").replace("‘", "'").replace("`", "'")
    t = t.replace("–", "-").replace("—", "-")
    t = re.sub(r"[_\-]+", " ", t)
    t = re.sub(r"[^\w\s']", " ", t, flags=re.UNICODE)
    t = re.sub(r"\s+", " ", t).strip()
    t = t.replace("'", "")
    return t


def canonical_title(raw: str) -> str:
    key = normalize_key(raw)
    if key in TITLE_ALIASES:
        return TITLE_ALIASES[key]
    # Essayer de retirer suffixes connus
    for suffix in (
        " full big band nestico",
        " full big band",
        " score sound",
        " piano part",
        " piano",
        " bass",
        " string bass",
        " parts 1",
        " parts 2",
        " parts 1 1",
        " scores",
        " shared",
        " 51 pages",
        " holmes 51 pages",
    ):
        if key.endswith(suffix):
            base = key[: -len(suffix)].strip()
            if base in TITLE_ALIASES:
                return TITLE_ALIASES[base]
            return base.title()
    return raw.strip() or "Sans titre"


# Patterns instrument → code poste (ordre : plus spécifique d’abord)
INSTRUMENT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(alto\s*sax(?:ophone)?\s*1|1(?:er|st|e)?\s*(?:sax\s*)?alto|saxalto\s*1|1st\s*e-?flat\s*alto)\b", re.I), "alto_1"),
    (re.compile(r"\b(alto\s*sax(?:ophone)?\s*2|2(?:eme|e|nd)?\s*(?:sax\s*)?alto|sax\s*alto\s*2|2nd\s*e-?flat\s*alto)\b", re.I), "alto_2"),
    # Alto sans numéro (souvent le 1er dans les éditions US)
    (re.compile(r"\b(e-?flat\s*alto\s*saxophone|alto\s*saxophone|alto\s*sax)\b", re.I), "alto_1"),
    (re.compile(r"\b(tenor\s*sax(?:ophone)?\s*1|1(?:er|st|e)?\s*(?:sax\s*)?tenor|1st\s*b-?flat\s*tenor)\b", re.I), "tenor_1"),
    (re.compile(r"\b(tenor\s*sax(?:ophone)?\s*2|2(?:eme|e|nd)?\s*(?:sax\s*)?tenor|2nd\s*b-?flat\s*tenor)\b", re.I), "tenor_2"),
    (re.compile(r"\b(b-?flat\s*tenor\s*saxophone|tenor\s*saxophone|tenor\s*sax)\b", re.I), "tenor_1"),
    (re.compile(r"\b(bari(?:tone)?\s*sax|sax\s*baryton|e-?flat\s*baritone\s*saxophone|baritone\s*sax)\b", re.I), "baryton"),
    (re.compile(r"\b(trumpet(?:\s*in\s*b[b♭])?\s*1|1(?:er|st|e)?\s*trumpet|1st\s*b-?flat\s*trumpet|trompette\s*1)\b", re.I), "trompette_1"),
    (re.compile(r"\b(trumpet(?:\s*in\s*b[b♭])?\s*2|2(?:eme|e|nd)?\s*trumpet|2nd\s*b-?flat\s*trumpet|trompette\s*2)\b", re.I), "trompette_2"),
    (re.compile(r"\b(trumpet(?:\s*in\s*b[b♭])?\s*3|3(?:eme|e|rd)?\s*trumpet|3rd\s*b-?flat\s*trumpet|trompette\s*3)\b", re.I), "trompette_3"),
    (re.compile(r"\b(trumpet(?:\s*in\s*b[b♭])?\s*4|4(?:eme|e|th)?\s*trumpet|4th\s*b-?flat\s*trumpet|trompette\s*4)\b", re.I), "trompette_4"),
    (re.compile(r"\b(trombone\s*1|1(?:er|st|e)?\s*trombone)\b", re.I), "trombone_1"),
    (re.compile(r"\b(trombone\s*2|2(?:eme|e|nd)?\s*trombone)\b", re.I), "trombone_2"),
    (re.compile(r"\b(trombone\s*3|3(?:eme|e|rd)?\s*trombone)\b", re.I), "trombone_3"),
    (re.compile(r"\b(trombone\s*4|4(?:eme|e|th)?\s*trombone|bass\s*trombone|4e\s*trombone)\b", re.I), "trombone_4"),
    (re.compile(r"\b(piano|piano\s*accompaniment|piano\s*part)\b", re.I), "piano"),
    (re.compile(r"\b(guitar|guitare|guitar\s*chords)\b", re.I), "guitare"),
    (re.compile(r"\b(string\s*bass|contrebasse|\bbass\b|\bbasse\b)\b", re.I), "basse"),
    (re.compile(r"\b(drums?|batterie)\b", re.I), "batterie"),
    (re.compile(r"\b(percussion|vibraphone|vibes)\b", re.I), "percussion"),
    (re.compile(r"\b(clarinet|clarinette|1st\s*b-?flat\s*clarinet)\b", re.I), "clarinette"),
    (re.compile(r"\b(vocal|chant|voix|voice)\b", re.I), "chant"),
    (re.compile(r"\b(conductor|conducteur|score|transposed\s*score|full\s*score)\b", re.I), "conducteur"),
    (re.compile(r"\b(flute|flute\s*in\s*c)\b", re.I), "autre"),
    (re.compile(r"\b(horn\s*in\s*f|f\s*horn|1st\s*f\s*horn)\b", re.I), "autre"),
    (re.compile(r"\b(baritone\s*t\.?\s*c\.?|baritone\s*horn|tuba)\b", re.I), "autre"),
]


def is_multipart_pack(filename: str) -> bool:
    """PDF regroupant plusieurs pupitres (Parts 1, Scores…) — à découper."""
    stem = Path(filename).stem.lower()
    if re.search(r"\bparts?\s*\d", stem):
        return True
    if re.search(r"\bscores?\b", stem) and "transposed" not in stem:
        # "Scores.pdf" packs, pas "Score.pdf" seul d'un instrument folder
        if "big band" in stem or "vocal" in stem:
            return True
    if re.search(r"\bfull\s+big\s+band\b", stem):
        return True
    if re.search(r"\d+\s*_?pages?\b", stem):
        return True
    return False


def detect_poste(filename: str) -> str | None:
    if is_multipart_pack(filename):
        return None
    stem = Path(filename).stem
    # Retirer préfixe numéro type "01 - "
    stem = re.sub(r"^\d+\s*[-_.]\s*", "", stem)
    for pattern, poste in INSTRUMENT_PATTERNS:
        if pattern.search(stem):
            return poste
    return None


def extract_piece_hint(filename: str, parent_dir: str | None) -> str:
    """Devine le titre du morceau depuis le nom de fichier ou le dossier parent."""
    stem = Path(filename).stem
    # Packs "BIG BAND + VOCAL. Title. Parts 1"
    m = re.match(
        r"^(?:BIG\s*BAND\s*\+\s*VOCAL\.?\s*)?(.+?)(?:\.\s*parts?\s*\d.*|\.\s*scores?.*)?$",
        stem,
        re.I,
    )
    if m and ("big band" in stem.lower() or "vocal" in stem.lower()):
        return canonical_title(m.group(1).strip(" ."))

    if parent_dir and parent_dir.lower() not in {
        "partitions basse",
        "partitions piano",
        "joy partitions basse",
        "2026",
        "_inbox",
    }:
        # Dossier = souvent le titre
        title_from_dir = parent_dir
        # Nettoyer suffixes dossier
        title_from_dir = re.sub(
            r",?\s*arr\..*$", "", title_from_dir, flags=re.I
        ).strip()
        if title_from_dir and not title_from_dir.lower().startswith("00-"):
            return canonical_title(title_from_dir)

    # Couper après " - " si la partie droite ressemble à un instrument
    if " - " in stem:
        left, right = stem.rsplit(" - ", 1)
        if detect_poste(right) or detect_poste(stem) or is_multipart_pack(filename):
            return canonical_title(left)
    # Patterns "Title - Instrument"
    m = re.match(r"^(.+?)\s+-\s+", stem)
    if m and (detect_poste(stem) or is_multipart_pack(filename)):
        return canonical_title(m.group(1))
    # Enlever suffixes instrument en fin de nom
    cleaned = stem
    for pat, _ in INSTRUMENT_PATTERNS:
        cleaned = pat.sub("", cleaned)
    cleaned = re.sub(r"\s*[-_]+\s*$", "", cleaned).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if len(cleaned) >= 3:
        return canonical_title(cleaned)
    return canonical_title(stem)


def should_skip(path: Path) -> bool:
    name = path.name.lower()
    if path.suffix.lower() in SKIP_EXT or path.suffix == "":
        # Fichier sans extension (ex. A_Foggy_day Google Doc export) : skip sauf pdf
        if path.suffix == "" and path.is_file():
            return True
        if path.suffix.lower() in SKIP_EXT:
            return True
    for frag in SKIP_NAME_FRAGMENTS:
        if frag in name:
            return True
    if name.endswith(".zip") or "bundle" in name:
        return True
    if "score & sound" in name or "score & sound" in name.lower():
        return True
    return False


@dataclass
class PartCandidate:
    poste: str
    sources: list[Path] = field(default_factory=list)
    kind: str = "pdf"  # pdf | images


@dataclass
class PieceBucket:
    title: str
    parts: dict[str, PartCandidate] = field(default_factory=dict)
    needs_split: list[Path] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


@dataclass
class HomogenizeReport:
    pieces: dict[str, PieceBucket] = field(default_factory=dict)
    orphan_needs_split: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    written: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "pieces": {
                slug: {
                    "title": b.title,
                    "parts": {
                        p: [str(s) for s in c.sources]
                        for p, c in b.parts.items()
                    },
                    "needs_split": [str(p) for p in b.needs_split],
                }
                for slug, b in sorted(self.pieces.items())
            },
            "orphan_needs_split": [str(p) for p in self.orphan_needs_split],
            "errors": self.errors,
            "written": self.written,
        }


def _page_sort_key(path: Path) -> tuple:
    """Ordre pages : Piano A, Piano B… ou Piano-1, Piano (2)-1…"""
    stem = path.stem
    # Lettre de page en fin (A, B, C…)
    m = re.search(r"\b([A-Za-z])$", stem)
    letter = m.group(1).upper() if m else ""
    # Numéros
    nums = [int(x) for x in re.findall(r"(\d+)", stem)]
    return (letter or "Z", nums, stem.lower())


def scan_inbox(inbox: Path) -> HomogenizeReport:
    report = HomogenizeReport()

    def bucket_for(title: str) -> PieceBucket:
        slug = slugify(title) or "morceau"
        if slug not in report.pieces:
            report.pieces[slug] = PieceBucket(title=title)
        return report.pieces[slug]

    files = [p for p in inbox.rglob("*") if p.is_file()]
    for path in files:
        if should_skip(path):
            continue
        rel_parts = path.relative_to(inbox).parts
        parent = rel_parts[-2] if len(rel_parts) > 1 else None
        # Collections par instrument
        if parent and parent.lower() in {
            "partitions basse",
            "joy partitions basse",
        }:
            title = extract_piece_hint(path.name, None)
            poste = "basse"
            b = bucket_for(title)
            _add_part(b, poste, path)
            continue
        if parent and parent.lower() == "partitions piano":
            title = extract_piece_hint(path.name, None)
            poste = "piano"
            b = bucket_for(title)
            _add_part(b, poste, path)
            continue

        # Sous-dossiers 2026/PieceName/
        if parent == "2026" and path.suffix.lower() in PDF_EXT | IMAGE_EXT:
            # fichier directement sous 2026 (zip déjà skip)
            continue
        if len(rel_parts) >= 3 and rel_parts[0] == "2026":
            parent = rel_parts[1]

        ext = path.suffix.lower()
        if ext not in PDF_EXT | IMAGE_EXT:
            continue

        title = extract_piece_hint(path.name, parent)
        poste = detect_poste(path.name)
        b = bucket_for(title)

        if poste:
            _add_part(b, poste, path)
        elif ext in IMAGE_EXT and re.search(r"score\s*\d*", path.stem, re.I):
            _add_part(b, "conducteur", path)
        elif ext in PDF_EXT:
            # PDF sans instrument détecté → à découper
            b.needs_split.append(path)
        else:
            b.skipped.append(str(path))

    return report


def _add_part(bucket: PieceBucket, poste: str, path: Path) -> None:
    ext = path.suffix.lower()
    kind = "images" if ext in IMAGE_EXT else "pdf"
    if poste not in bucket.parts:
        bucket.parts[poste] = PartCandidate(poste=poste, kind=kind)
    cand = bucket.parts[poste]
    # Si on avait des images et on reçoit un PDF (ou l’inverse), on garde les deux
    # sources ; à l’écriture on préférera le PDF s’il existe.
    if kind == "pdf":
        cand.kind = "pdf"
    cand.sources.append(path)


def write_sorted(
    report: HomogenizeReport,
    out_dir: Path,
    *,
    dry_run: bool = False,
) -> HomogenizeReport:
    out_dir = out_dir.resolve()
    needs_dir = out_dir / "_needs_split"
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        needs_dir.mkdir(parents=True, exist_ok=True)

    for slug, bucket in sorted(report.pieces.items()):
        piece_dir = out_dir / slug
        if not dry_run:
            piece_dir.mkdir(parents=True, exist_ok=True)

        for poste, cand in sorted(bucket.parts.items()):
            dest = piece_dir / f"{poste}.pdf"
            try:
                pdfs = [s for s in cand.sources if s.suffix.lower() in PDF_EXT]
                imgs = [s for s in cand.sources if s.suffix.lower() in IMAGE_EXT]
                if pdfs:
                    # Garder le plus gros PDF (souvent la meilleure qualité)
                    best = max(pdfs, key=lambda p: p.stat().st_size)
                    if not dry_run:
                        shutil.copy2(best, dest)
                    report.written.append(f"{slug}/{poste}.pdf <- {best.name}")
                elif imgs:
                    ordered = sorted(imgs, key=_page_sort_key)
                    if dry_run:
                        report.written.append(
                            f"{slug}/{poste}.pdf <- {len(ordered)} images"
                        )
                    else:
                        data = images_to_pdf_bytes(ordered)
                        dest.write_bytes(data)
                        report.written.append(
                            f"{slug}/{poste}.pdf <- {len(ordered)} images"
                        )
            except Exception as exc:
                report.errors.append(f"{slug}/{poste}: {exc}")

        for src in bucket.needs_split:
            dest = needs_dir / f"{slug}__{src.name}"
            if not dry_run:
                shutil.copy2(src, dest)
            report.written.append(f"_needs_split/{dest.name}")

        if not dry_run:
            meta = {
                "title": bucket.title,
                "slug": slug,
                "parts": sorted(bucket.parts.keys()),
                "needs_split": [p.name for p in bucket.needs_split],
                "sources": {
                    p: [str(s) for s in c.sources]
                    for p, c in bucket.parts.items()
                },
            }
            (piece_dir / "_meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    # Rapport
    if not dry_run:
        (out_dir / "_report.json").write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (out_dir / "_report.md").write_text(
            _render_markdown(report), encoding="utf-8"
        )
    return report


def _render_markdown(report: HomogenizeReport) -> str:
    lines = [
        "# Rapport d’homogénéisation répertoire",
        "",
        f"- Morceaux : **{len(report.pieces)}**",
        f"- Fichiers écrits : **{len(report.written)}**",
        f"- Erreurs : **{len(report.errors)}**",
        "",
        "## Morceaux",
        "",
    ]
    for slug, b in sorted(report.pieces.items(), key=lambda x: x[1].title.lower()):
        lines.append(f"### {b.title} (`{slug}`)")
        if b.parts:
            lines.append(
                "- Postes : "
                + ", ".join(f"`{p}`" for p in sorted(b.parts.keys()))
            )
        if b.needs_split:
            lines.append(
                f"- À découper manuellement : {len(b.needs_split)} PDF"
            )
        lines.append("")
    if report.errors:
        lines.append("## Erreurs")
        lines.append("")
        for e in report.errors:
            lines.append(f"- {e}")
    return "\n".join(lines) + "\n"
