"""
Crée les fiches Piece + Part à partir de media/repertoire/_sorted/.

Usage :
  DJANGO_SETTINGS_MODULE=config.settings.prod \\
    python manage.py publish_sorted_repertoire

  # Brouillons (non visibles musiciens) :
    python manage.py publish_sorted_repertoire --draft

  # Ne pas écraser les PDF déjà en base :
    python manage.py publish_sorted_repertoire --skip-existing-parts
"""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand
from django.db import transaction

from repertoire.models import Part, PartPoste, Piece

VALID_POSTES = {c.value for c in PartPoste}

# Fragments mal découpés à ne pas publier comme morceaux autonomes
SKIP_SLUG_PREFIXES = (
    "vocal-duet-",
    "vocal-solo-",
    "route-66-",
    "sing-sing-sing-part",
    "the-frim-fram-sauce-",
    "the-man-i-love-arr",
    "the-man-i-love-music",
    "the-main-i-love",
    "night-and-day-solo",
    "night-and-day-vocals",
    "no-moon-at-all-a",
    "no-moon-at-all-b",
    "lovemeorleaveme",
    "itcould-",
    "deroule",
)


def _should_skip_slug(slug: str) -> bool:
    s = slug.lower()
    return any(s.startswith(p) or s == p for p in SKIP_SLUG_PREFIXES)


class Command(BaseCommand):
    help = "Importe _sorted/<slug>/<poste>.pdf → Piece + Part en base"

    def add_arguments(self, parser):
        parser.add_argument(
            "--sorted-dir",
            default="",
            help="Dossier source (défaut : MEDIA_ROOT/repertoire/_sorted)",
        )
        parser.add_argument(
            "--draft",
            action="store_true",
            help="Créer les morceaux non publiés (is_published=False)",
        )
        parser.add_argument(
            "--skip-existing-parts",
            action="store_true",
            help="Ne pas remplacer un PDF déjà présent pour un poste",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche ce qui serait fait sans écrire en base",
        )

    def handle(self, *args, **options):
        root = Path(
            options["sorted_dir"]
            or Path(settings.MEDIA_ROOT) / "repertoire" / "_sorted"
        )
        if not root.is_dir():
            self.stderr.write(self.style.ERROR(f"Dossier introuvable : {root}"))
            return

        publish = not options["draft"]
        dry = options["dry_run"]
        skip_existing = options["skip_existing_parts"]

        dirs = sorted(
            d
            for d in root.iterdir()
            if d.is_dir() and not d.name.startswith("_")
        )
        created_pieces = updated_pieces = 0
        created_parts = updated_parts = 0
        skipped = 0

        for piece_dir in dirs:
            meta_path = piece_dir / "_meta.json"
            title = piece_dir.name.replace("-", " ").title()
            slug = piece_dir.name
            if meta_path.is_file():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    title = meta.get("title") or title
                    slug = meta.get("slug") or slug
                except json.JSONDecodeError:
                    pass

            if _should_skip_slug(slug) or _should_skip_slug(piece_dir.name):
                self.stdout.write(f"  (ignoré fragment) {piece_dir.name}")
                skipped += 1
                continue

            pdfs = sorted(
                p
                for p in piece_dir.glob("*.pdf")
                if p.stem in VALID_POSTES
            )
            if not pdfs:
                self.stdout.write(f"  (vide) {slug}")
                skipped += 1
                continue

            if dry:
                self.stdout.write(
                    f"  {'PUB' if publish else 'draft'} {title} "
                    f"({len(pdfs)} parts) ← {piece_dir.name}"
                )
                created_pieces += 1
                created_parts += len(pdfs)
                continue

            with transaction.atomic():
                piece, was_created = Piece.objects.get_or_create(
                    slug=slug,
                    defaults={
                        "title": title,
                        "is_published": publish,
                    },
                )
                if was_created:
                    created_pieces += 1
                else:
                    updated = False
                    if piece.title != title:
                        piece.title = title
                        updated = True
                    if publish and not piece.is_published:
                        piece.is_published = True
                        updated = True
                    if updated:
                        piece.save()
                        updated_pieces += 1

                for pdf_path in pdfs:
                    poste = pdf_path.stem
                    part = Part.objects.filter(piece=piece, poste=poste).first()
                    if part and skip_existing and part.file:
                        skipped += 1
                        continue
                    with pdf_path.open("rb") as fh:
                        django_file = File(fh, name=f"{slug}-{poste}.pdf")
                        if part is None:
                            part = Part(piece=piece, poste=poste)
                            part.file.save(
                                f"{slug}-{poste}.pdf", django_file, save=True
                            )
                            part.source_name = pdf_path.name
                            part.save(update_fields=["source_name", "updated_at"])
                            created_parts += 1
                        else:
                            if part.file:
                                part.file.delete(save=False)
                            part.file.save(
                                f"{slug}-{poste}.pdf", django_file, save=True
                            )
                            part.source_name = pdf_path.name
                            part.save(update_fields=["source_name", "updated_at"])
                            updated_parts += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Morceaux +{created_pieces} / ~{updated_pieces} · "
                f"Parts +{created_parts} / ~{updated_parts} · "
                f"ignorés {skipped}"
                + (" (dry-run)" if dry else "")
            )
        )
        if not dry:
            total = Piece.objects.filter(is_published=True).count()
            self.stdout.write(f"Publiés en base : {total}")
