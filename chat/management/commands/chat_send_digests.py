from __future__ import annotations

from collections import defaultdict

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Max
from django.core.management.base import BaseCommand

from chat.models import ChatMembership, ChatMessage
from users.phone import normalize_phone
from users.sms import send_sms

User = get_user_model()


class Command(BaseCommand):
    help = "Envoie les digests SMS des nouveaux messages de chat."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche les SMS sans les envoyer.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        site_url = getattr(settings, "SITE_URL", "https://jazz-orchestra-yonnais.fr").rstrip(
            "/"
        )
        chat_url = f"{site_url}/chat/"

        memberships = (
            ChatMembership.objects.filter(
                subscribed=True,
                left_at__isnull=True,
                user__is_active=True,
                user__phone__gt="",
            )
            .select_related("user", "room")
            .exclude(user__phone="")
        )

        # Group by user
        by_user: dict[int, list[ChatMembership]] = defaultdict(list)
        for m in memberships:
            by_user[m.user_id].append(m)

        sent = 0
        for user_id, user_memberships in by_user.items():
            user = user_memberships[0].user
            phone = normalize_phone(user.phone or "")
            if not phone:
                continue

            room_summaries: list[tuple[str, int]] = []
            updates: list[tuple[ChatMembership, int]] = []

            for m in user_memberships:
                qs = ChatMessage.objects.filter(
                    room_id=m.room_id,
                    deleted_at__isnull=True,
                    pk__gt=m.last_digested_message_id,
                ).exclude(author_id=user_id)
                count = qs.count()
                if count == 0:
                    continue
                max_id = qs.aggregate(m=Max("pk"))["m"] or m.last_digested_message_id
                room_summaries.append((m.room.title, count))
                updates.append((m, max_id))

            if not room_summaries:
                continue

            total = sum(c for _, c in room_summaries)
            # Keep SMS short
            parts = [f"{title} ({n})" for title, n in room_summaries[:3]]
            extra = len(room_summaries) - 3
            rooms_txt = ", ".join(parts)
            if extra > 0:
                rooms_txt += f" +{extra}"
            body = f"JOY — {total} msg : {rooms_txt}. {chat_url}"

            if dry_run:
                self.stdout.write(f"[dry-run] {phone}: {body}")
            else:
                try:
                    send_sms(phone, body)
                except Exception as exc:  # noqa: BLE001
                    self.stderr.write(f"Échec SMS {user}: {exc}")
                    continue
                for membership, max_id in updates:
                    membership.last_digested_message_id = max_id
                    membership.save(update_fields=["last_digested_message_id"])
                sent += 1

        self.stdout.write(self.style.SUCCESS(f"Digests envoyés : {sent}"))
