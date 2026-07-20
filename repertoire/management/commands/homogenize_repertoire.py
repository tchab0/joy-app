"""
Homogénéise l’inbox Drive en arborescence :
  media/repertoire/_sorted/<slug>/<poste>.pdf

- Fusionne les JPG multi-pages par instrument
- Mappe les noms de fichiers vers les postes JOY
- Place les PDF multi-pupitres non identifiés dans _needs_split/
- Produit _report.md / _report.json

Usage :
  cd /srv/jazz-orchestra-yonnais/repo
  DJANGO_SETTINGS_MODULE=config.settings.prod \\
    python manage.py homogenize_repertoire
  # Aperçu sans écrire :
    python manage.py homogenize_repertoire --dry-run
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from repertoire.homogenize import scan_inbox, write_sorted


class Command(BaseCommand):
    help = "Trie et homogénéise l’inbox Drive → _sorted/<morceau>/<poste>.pdf"

    def add_arguments(self, parser):
        parser.add_argument(
            "--inbox",
            default="",
            help="Dossier source (défaut : MEDIA_ROOT/repertoire/_inbox)",
        )
        parser.add_argument(
            "--out",
            default="",
            help="Dossier cible (défaut : MEDIA_ROOT/repertoire/_sorted)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Analyse seulement, n’écrit pas les fichiers",
        )

    def handle(self, *args, **options):
        media = Path(settings.MEDIA_ROOT)
        inbox = Path(options["inbox"] or media / "repertoire" / "_inbox")
        out = Path(options["out"] or media / "repertoire" / "_sorted")
        dry = options["dry_run"]

        if not inbox.is_dir():
            self.stderr.write(self.style.ERROR(f"Inbox introuvable : {inbox}"))
            return

        self.stdout.write(f"Inbox : {inbox}")
        self.stdout.write(f"Sortie : {out}{' (dry-run)' if dry else ''}")

        report = scan_inbox(inbox)
        report = write_sorted(report, out, dry_run=dry)

        n_parts = sum(len(b.parts) for b in report.pieces.values())
        n_split = sum(len(b.needs_split) for b in report.pieces.values())
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(report.pieces)} morceaux · {n_parts} parties "
                f"· {n_split} PDF à découper · {len(report.errors)} erreurs"
            )
        )
        if not dry:
            self.stdout.write(f"Rapport : {out / '_report.md'}")
        else:
            for slug, b in sorted(
                report.pieces.items(), key=lambda x: x[1].title.lower()
            )[:30]:
                self.stdout.write(
                    f"  · {b.title}: {', '.join(sorted(b.parts.keys())) or '—'}"
                    + (f" (+{len(b.needs_split)} split)" if b.needs_split else "")
                )
            if len(report.pieces) > 30:
                self.stdout.write(f"  … et {len(report.pieces) - 30} autres")
