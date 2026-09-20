from __future__ import annotations

from django.core.management.base import BaseCommand

from events.models import Event
from planning.services import (
    build_morning_reminder_message,
    events_due_for_morning_reminder,
    present_musicians_for_event,
    resolve_only_user,
    send_event_morning_reminders,
)


class Command(BaseCommand):
    help = (
        "Le matin d’un événement confirmé : rappel joyeux aux musiciens "
        "positionnés présents (feuille de route, adresse, météo)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Liste les événements / destinataires sans envoyer.",
        )
        parser.add_argument(
            "--force-event",
            type=int,
            default=0,
            help="Forcer l’envoi pour un Event pk (ignore le jour J et le flag déjà envoyé).",
        )
        parser.add_argument(
            "--only-user",
            type=str,
            default="",
            help="Restreindre à un destinataire (pk, username ou e-mail) — essais.",
        )
        parser.add_argument(
            "--mark",
            action="store_true",
            help="Horodater morning_reminder_sent_at même avec --only-user.",
        )
        parser.add_argument(
            "--no-mark",
            action="store_true",
            help="Ne pas horodater morning_reminder_sent_at.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        force_pk = int(options["force_event"] or 0)
        only_spec = (options["only_user"] or "").strip()
        only_user = resolve_only_user(only_spec) if only_spec else None
        if only_spec and only_user is None:
            self.stderr.write(
                self.style.ERROR(f"Utilisateur introuvable : {only_spec!r}")
            )
            return

        # Essai ciblé : ne pas bloquer l’envoi collectif, sauf --mark explicite.
        if options["no_mark"]:
            mark_sent = False
        elif only_user is not None and not options["mark"]:
            mark_sent = False
        else:
            mark_sent = True

        if force_pk:
            events = list(
                Event.objects.filter(pk=force_pk)
                .exclude(statut=Event.Statut.ANNULE)
                .select_related("type", "venue")
            )
        else:
            events = events_due_for_morning_reminder()

        if not events:
            self.stdout.write("Aucun événement à traiter.")
            return

        if dry_run:
            for event in events:
                parts = list(present_musicians_for_event(event))
                title, body, url = build_morning_reminder_message(event)
                who = parts
                if only_user is not None:
                    matched = [p for p in parts if p.user_id == only_user.pk]
                    who = matched or parts[:0]
                    n = len(matched) or 1  # essai staff même hors liste
                else:
                    n = len(who)
                self.stdout.write(
                    f"[dry-run] #{event.pk} « {event.titre} » → {n} destinataire(s)"
                )
                self.stdout.write(f"  title: {title}")
                self.stdout.write(f"  url: {url}")
                for line in body.splitlines():
                    self.stdout.write(f"  | {line}")
            return

        total = send_event_morning_reminders(
            events,
            only_user=only_user,
            mark_sent=mark_sent,
        )
        marked = "" if mark_sent else " (non marqué)"
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(events)} événement(s), {total} notification(s) envoyée(s){marked}."
            )
        )
