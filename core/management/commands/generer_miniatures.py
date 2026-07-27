"""Génère les miniatures WebP manquantes pour la grille Médias."""

from django.core.management.base import BaseCommand
from django.db.models import Q

from core.models import MediaItem
from core.utils_compression import compresser_media


class Command(BaseCommand):
    help = "Génère miniature (~400w WebP) pour les photos sans vignette."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Regénère aussi les miniatures déjà présentes.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Limiter le nombre de médias traités (0 = tous).",
        )

    def handle(self, *args, **options):
        qs = MediaItem.objects.filter(type="photo").filter(
            Q(fichier__isnull=False) & ~Q(fichier="")
            | Q(fichier_edite__isnull=False) & ~Q(fichier_edite="")
        )
        if not options["all"]:
            qs = qs.filter(Q(miniature="") | Q(miniature__isnull=True))

        qs = qs.order_by("pk")
        if options["limit"]:
            ids = list(qs.values_list("pk", flat=True)[: options["limit"]])
            qs = MediaItem.objects.filter(pk__in=ids).order_by("pk")

        total = qs.count()
        self.stdout.write(f"Traitement de {total} photo(s)…")
        ok = 0
        for media in qs.iterator():
            try:
                compresser_media(media)
                media.refresh_from_db(fields=["miniature"])
                if media.miniature:
                    ok += 1
                    self.stdout.write(f"  OK #{media.pk} {media.titre[:40]}")
                else:
                    self.stdout.write(self.style.WARNING(f"  skip #{media.pk}"))
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"  ERR #{media.pk}: {exc}"))
        self.stdout.write(self.style.SUCCESS(f"Terminé : {ok} miniature(s)."))
