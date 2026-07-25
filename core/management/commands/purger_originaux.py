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

        original_name = media.fichier.name
        original_storage = media.fichier.storage
        media.fichier.name = rel_compresse
        media.save(update_fields=["fichier"])

        if (
            original_name
            and original_name != rel_compresse
            and not MediaItem.objects.filter(fichier=original_name).exists()
            and original_storage.exists(original_name)
        ):
            original_storage.delete(original_name)
        return True

    def _supprimer_tout(self, media: MediaItem) -> bool:
        """Supprime fichier, miniature et sidecar compressé pour un média refusé."""
        compressé = media.chemin_compresse()
        rel_compresse = (
            compressé.relative_to(Path(media._media_root())).as_posix()
            if compressé
            else ""
        )
        fichier_name = media.fichier.name if media.fichier else ""
        fichier_storage = media.fichier.storage if media.fichier else None
        miniature_name = media.miniature.name if media.miniature else ""
        miniature_storage = media.miniature.storage if media.miniature else None

        update_fields = []
        if fichier_name:
            media.fichier = ""
            update_fields.append("fichier")
        if miniature_name:
            media.miniature = ""
            update_fields.append("miniature")

        if update_fields:
            # Le DB ne doit plus référencer les fichiers avant leur suppression :
            # une erreur de sauvegarde ne peut ainsi jamais créer de lien cassé.
            media.save(update_fields=update_fields)

        if (
            fichier_name
            and not MediaItem.objects.filter(fichier=fichier_name).exists()
            and fichier_storage.exists(fichier_name)
        ):
            fichier_storage.delete(fichier_name)

        if (
            miniature_name
            and not MediaItem.objects.filter(miniature=miniature_name).exists()
            and miniature_storage.exists(miniature_name)
        ):
            miniature_storage.delete(miniature_name)

        if (
            compressé
            and rel_compresse != fichier_name
            and not MediaItem.objects.filter(fichier=rel_compresse).exists()
            and compressé.exists()
        ):
            compressé.unlink()

        return bool(update_fields or compressé)
