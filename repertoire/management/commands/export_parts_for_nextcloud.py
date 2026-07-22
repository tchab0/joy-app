"""
Exporte les PDF Part publiés vers le dossier Nextcloud (format MobileSheets).

Arborescence :
  <dest>/Partitions/<slug>/<poste>.pdf

Par défaut n'écrase PAS un fichier cloud plus récent que la Part en base
(préserve annotations embarquées / edits MobileSheets).

Usage :
  DJANGO_SETTINGS_MODULE=config.settings.prod \\
    python manage.py export_parts_for_nextcloud

  python manage.py export_parts_for_nextcloud --force
  python manage.py export_parts_for_nextcloud --dry-run
"""

from __future__ import annotations

import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from repertoire.models import Part


DEFAULT_DEST = Path("/srv/jazz-orchestra-yonnais/data/nextcloud/scores")


class Command(BaseCommand):
    help = "Exporte Part PDF → Nextcloud scores/Partitions/<slug>/<poste>.pdf"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dest",
            default="",
            help=f"Racine scores (défaut : {DEFAULT_DEST})",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Écraser même si le fichier cloud est plus récent",
        )
        parser.add_argument(
            "--include-drafts",
            action="store_true",
            help="Inclure les morceaux non publiés",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche sans écrire",
        )

    def handle(self, *args, **options):
        dest_root = Path(options["dest"] or DEFAULT_DEST).resolve()
        partitions = dest_root / "Partitions"
        mslib = dest_root / "MobileSheets-Lib"
        dry = options["dry_run"]
        force = options["force"]

        qs = Part.objects.select_related("piece").filter(file__isnull=False)
        if not options["include_drafts"]:
            qs = qs.filter(piece__is_published=True)
        qs = qs.exclude(file="")

        media_root = Path(settings.MEDIA_ROOT)

        created = updated = skipped = missing = 0

        if not dry:
            partitions.mkdir(parents=True, exist_ok=True)
            mslib.mkdir(parents=True, exist_ok=True)
            readme = partitions / "README-MobileSheets.txt"
            if not readme.exists():
                readme.write_text(
                    "Structure : <slug>/<poste>.pdf — voir deploy/nextcloud/README.md\n"
                    "Avant d'annoter : verrouiller le fichier dans Nextcloud "
                    "(lecture seule pour les autres).\n",
                    encoding="utf-8",
                )

        for part in qs.iterator():
            slug = part.piece.slug
            poste = part.poste
            rel = Path(part.file.name)
            src = media_root / rel
            if not src.is_file():
                self.stderr.write(f"MANQUANT {slug}/{poste} → {src}")
                missing += 1
                continue

            target = partitions / slug / f"{poste}.pdf"
            action = "CREATE"
            if target.is_file():
                if not force:
                    src_mtime = src.stat().st_mtime
                    dst_mtime = target.stat().st_mtime
                    # Cloud plus récent → probablement annoté : on préserve
                    if dst_mtime >= src_mtime:
                        skipped += 1
                        continue
                action = "UPDATE"

            self.stdout.write(f"{action} {target.relative_to(dest_root)}")
            if dry:
                if action == "CREATE":
                    created += 1
                else:
                    updated += 1
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            if action == "CREATE":
                created += 1
            else:
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"OK dest={dest_root} created={created} updated={updated} "
                f"skipped={skipped} missing={missing}"
            )
        )
