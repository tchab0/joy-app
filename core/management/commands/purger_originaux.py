from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import MediaItem


class Command(BaseCommand):
    help = (
        "Purge les fichiers médias : "
        "originaux publiés (>30j) remplacés par édité/compressé, "
        "fichiers refusés (>7j)."
    )

    def handle(self, *args, **options):
        maintenant = timezone.now()
        supprimes = 0

        seuil_publie = maintenant - timedelta(days=30)
        publies = MediaItem.objects.filter(
            statut="publie",
            soumis_le__lte=seuil_publie,
        )

        for m in publies:
            try:
                if self._purger_original(m):
                    supprimes += 1
                    self.stdout.write(f"  [publie] original purgé #{m.pk} — {m.titre}")
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

    def _purger_original(self, media: MediaItem) -> bool:
        """
        Après 30 j : supprimer l'original lourd.
        Ordre de bascule pour `fichier` (source de retouche) :
          1. compressé dérivé de la source (stem du fichier, pas de l'édité)
          2. sinon ne rien faire si seul l'édité / son compressé restent
        L'édité et son sidecar d'affichage sont conservés.
        """
        if not media.fichier:
            return False

        name = media.fichier.name.replace("\\", "/")
        # Déjà basculé dans compresses/
        if "/compresses/" in f"/{name}":
            return False
        edite_name = media.fichier_edite.name if media.fichier_edite else ""
        if edite_name and media.fichier.name == edite_name:
            return False

        dest_dir = Path(settings.MEDIA_ROOT) / "medias" / "compresses"
        stem = Path(media.fichier.name).stem
        # Compressé de la SOURCE (pas celui de l'édité, stem différent)
        source_compress = dest_dir / f"{stem}.webp"
        original_path = Path(media.fichier.path)

        if not source_compress.exists():
            return False

        if original_path.exists() and original_path.resolve() != source_compress.resolve():
            if not edite_name or original_path.resolve() != Path(media.fichier_edite.path).resolve():
                original_path.unlink(missing_ok=True)

        rel = source_compress.relative_to(Path(settings.MEDIA_ROOT)).as_posix()
        media.fichier.name = rel
        media.save(update_fields=["fichier"])
        return True

    def _supprimer_tout(self, media: MediaItem) -> bool:
        """Supprime fichier, édité, miniature et sidecar compressé pour un média refusé."""
        touched = False

        compressé = media.chemin_compresse()
        if compressé and compressé.exists():
            compressé.unlink()
            touched = True

        if media.fichier:
            media.fichier.delete(save=False)
            media.fichier = ""
            touched = True

        if media.fichier_edite:
            media.fichier_edite.delete(save=False)
            media.fichier_edite = ""
            touched = True

        if media.miniature:
            media.miniature.delete(save=False)
            media.miniature = ""
            touched = True

        if touched:
            media.save(update_fields=["fichier", "fichier_edite", "miniature"])
        return touched
