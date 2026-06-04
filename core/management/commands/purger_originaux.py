from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from core.models import MediaItem


class Command(BaseCommand):
    help = "Supprime les fichiers originaux après validation (30j) ou refus (7j)"

    def handle(self, *args, **options):
        maintenant = timezone.now()
        supprimes = 0

        # Publiés depuis plus de 30 jours
        seuil_publie = maintenant - timedelta(days=30)
        publies = MediaItem.objects.filter(
            statut="publie",
            fichier__isnull=False,
            soumis_le__lte=seuil_publie,
        ).exclude(fichier="")

        for m in publies:
            if m.fichier_compresse:
                try:
                    m.fichier.delete(save=False)
                    m.fichier = ""
                    m.save(update_fields=["fichier"])
                    supprimes += 1
                    self.stdout.write(f"  [publie] supprimé original #{m.pk} — {m.titre}")
                except Exception as e:
                    self.stderr.write(f"  ERREUR #{m.pk}: {e}")

        # Refusés depuis plus de 7 jours
        seuil_refuse = maintenant - timedelta(days=7)
        refuses = MediaItem.objects.filter(
            statut="refuse",
            soumis_le__lte=seuil_refuse,
        )
        for m in refuses:
            try:
                if m.fichier:
                    m.fichier.delete(save=False)
                    m.fichier = ""
                if m.fichier_compresse:
                    m.fichier_compresse.delete(save=False)
                    m.fichier_compresse = ""
                m.save(update_fields=["fichier", "fichier_compresse"])
                supprimes += 1
                self.stdout.write(f"  [refuse] supprimé #{m.pk} — {m.titre}")
            except Exception as e:
                self.stderr.write(f"  ERREUR #{m.pk}: {e}")

        self.stdout.write(self.style.SUCCESS(f"Terminé — {supprimes} fichier(s) supprimé(s)"))
