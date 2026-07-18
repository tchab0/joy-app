from datetime import timedelta
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import MediaItem


class Command(BaseCommand):
    help = (
        "Purge les fichiers médias : "
        "originaux publiés remplacés par la version compressée (>30j), "
        "fichiers refusés (>7j)."
    )

    def handle(self, *args, **options):
        maintenant = timezone.now()
        supprimes = 0

        seuil_publie = maintenant - timedelta(days=30)
        publies = MediaItem.objects.filter(
            statut="publie",
            fichier__isnull=False,
            soumis_le__lte=seuil_publie,
        ).exclude(fichier="")

        for m in publies:
            try:
                if self._remplacer_par_compresse(m):
                    supprimes += 1
                    self.stdout.write(f"  [publie] original remplacé par compressé #{m.pk} — {m.titre}")
            except Exception as e:
                self.stderr.write(f"  ERREUR #{m.pk}: {e}")

        seuil_refuse = maintenant - timedelta(days=7)
        refuses = MediaItem.objects.filter(
            statut="refuse",
            soumis_le__lte=seuil_refuse,
        )
        for m in refuses:
            try:
                if self._supprimer_tout(m):
                    supprimes += 1
                    self.stdout.write(f"  [refuse] supprimé #{m.pk} — {m.titre}")
            except Exception as e:
                self.stderr.write(f"  ERREUR #{m.pk}: {e}")

        self.stdout.write(self.style.SUCCESS(f"Terminé — {supprimes} média(s) traité(s)"))

    def _remplacer_par_compresse(self, media: MediaItem) -> bool:
        """Si un sidecar compressé existe et que fichier pointe encore sur l'original, bascule."""
        compressé = media.chemin_compresse()
        if not compressé:
            return False

        rel_compresse = media.chemin_compresse_relatif()
        if media.fichier.name == rel_compresse:
            return False

        original_path = Path(media.fichier.path)
        if original_path.exists() and original_path.resolve() != compressé.resolve():
            original_path.unlink()

        media.fichier.name = rel_compresse
        media.save(update_fields=["fichier"])
        return True

    def _supprimer_tout(self, media: MediaItem) -> bool:
        """Supprime fichier, miniature et sidecar compressé pour un média refusé."""
        touched = False

        compressé = media.chemin_compresse()
        if compressé and compressé.exists():
            compressé.unlink()
            touched = True

        if media.fichier:
            media.fichier.delete(save=False)
            media.fichier = ""
            touched = True

        if media.miniature:
            media.miniature.delete(save=False)
            media.miniature = ""
            touched = True

        if touched:
            media.save(update_fields=["fichier", "miniature"])
        return touched
