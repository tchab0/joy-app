"""Répare le flood de digests chat (curseurs bloqués + inbox en double)."""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Max
from django.utils import timezone


class Command(BaseCommand):
    help = (
        "Avance last_digested_message_id au tip de chaque salon et marque lues "
        "les notifications inbox « JOY — Chat » encore non lues (flood digest)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche les compteurs sans écrire.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        from chat.models import ChatMembership, ChatMessage
        from users.models import UserNotification
        from users.nav_cache import invalidate_nav_banner_cache

        tips = {
            row["room_id"]: row["tip"] or 0
            for row in ChatMessage.objects.filter(deleted_at__isnull=True)
            .values("room_id")
            .annotate(tip=Max("pk"))
        }

        memberships = list(ChatMembership.objects.all().only(
            "pk", "room_id", "user_id", "last_digested_message_id"
        ))
        to_advance = []
        for m in memberships:
            tip = tips.get(m.room_id, 0)
            if tip > m.last_digested_message_id:
                to_advance.append((m, tip))

        flood_qs = UserNotification.objects.filter(
            read_at__isnull=True,
            title="JOY — Chat",
        )
        flood_count = flood_qs.count()
        user_ids = list(flood_qs.values_list("user_id", flat=True).distinct())

        self.stdout.write(
            f"Curseurs à avancer : {len(to_advance)} / {len(memberships)}"
        )
        self.stdout.write(f"Inbox « JOY — Chat » non lues : {flood_count}")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry-run — aucune écriture."))
            return

        now = timezone.now()
        for m, tip in to_advance:
            m.last_digested_message_id = tip
            m.save(update_fields=["last_digested_message_id"])

        updated = flood_qs.update(read_at=now)
        for uid in user_ids:
            invalidate_nav_banner_cache(uid)

        self.stdout.write(
            self.style.SUCCESS(
                f"OK — {len(to_advance)} curseur(s), {updated} notif(s) marquées lues."
            )
        )
