from __future__ import annotations

from collections import defaultdict

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from chat.models import ChatMembership, ChatMessage
from chat.services import message_targets_instant_notify
from users.notify import notify_users

User = get_user_model()


class Command(BaseCommand):
    help = "Envoie les digests d’alertes (push ou e-mail) des nouveaux messages de chat."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche les digests sans les envoyer.",
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
            )
            .select_related("user", "room")
        )

        by_user: dict[int, list[ChatMembership]] = defaultdict(list)
        for m in memberships:
            by_user[m.user_id].append(m)

        sent = 0
        for user_id, user_memberships in by_user.items():
            user = user_memberships[0].user

            room_summaries: list[tuple[str, int]] = []
            updates: list[tuple[ChatMembership, int]] = []

            for m in user_memberships:
                qs = (
                    ChatMessage.objects.filter(
                        room_id=m.room_id,
                        deleted_at__isnull=True,
                        pk__gt=m.last_digested_message_id,
                    )
                    .exclude(author_id=user_id)
                    .select_related("reply_to")
                )
                msgs = list(qs.order_by("pk"))
                if not msgs:
                    continue
                max_id = msgs[-1].pk
                # Déjà notifiés en instantané (@mention ou réponse) → hors digest
                digest_msgs = [
                    msg
                    for msg in msgs
                    if not message_targets_instant_notify(
                        msg, user_id, username=user.username
                    )
                ]
                updates.append((m, max_id))
                if not digest_msgs:
                    continue
                room_summaries.append((m.room.title, len(digest_msgs)))

            if not room_summaries:
                # Avancer le curseur même si tout a déjà été notifié en instantané
                if updates and not dry_run:
                    for membership, max_id in updates:
                        membership.last_digested_message_id = max_id
                        membership.save(update_fields=["last_digested_message_id"])
                continue

            total = sum(c for _, c in room_summaries)
            parts = [f"{title} ({n})" for title, n in room_summaries[:3]]
            extra = len(room_summaries) - 3
            rooms_txt = ", ".join(parts)
            if extra > 0:
                rooms_txt += f" +{extra}"
            body = f"{total} nouveau(x) message(s) : {rooms_txt}."
            title = "JOY — Chat"

            if dry_run:
                dest = user.email or f"user:{user.pk}"
                self.stdout.write(f"[dry-run] {dest}: {title} — {body} {chat_url}")
            else:
                n = notify_users(
                    [user],
                    title=title,
                    body=body,
                    url="/chat/",
                )
                if not n:
                    self.stderr.write(f"Échec digest {user}")
                    continue
                for membership, max_id in updates:
                    membership.last_digested_message_id = max_id
                    membership.save(update_fields=["last_digested_message_id"])
                sent += 1

        self.stdout.write(self.style.SUCCESS(f"Digests envoyés : {sent}"))
