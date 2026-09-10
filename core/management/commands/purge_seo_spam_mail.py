"""Purge silencieuse des mails SEO rédigés en anglais (IMAP)."""

from __future__ import annotations

import email
import imaplib
import logging
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.mail_spam import extract_text_from_message, is_english_seo_spam

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Supprime silencieusement (sans notification) les messages IMAP "
        "contenant « SEO » et rédigés en anglais."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Liste les messages ciblés sans les supprimer.",
        )
        parser.add_argument(
            "--mailbox",
            default=None,
            help="Boîte IMAP (défaut: settings.IMAP_MAILBOX, sinon INBOX).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=200,
            help="Nombre max de messages récents à inspecter (défaut 200).",
        )

    def handle(self, *args, **options):
        host = getattr(settings, "IMAP_HOST", "") or "imap.hostinger.com"
        port = int(getattr(settings, "IMAP_PORT", 993) or 993)
        user = (
            getattr(settings, "IMAP_USER", "")
            or getattr(settings, "EMAIL_HOST_USER", "")
            or ""
        ).strip()
        password = (
            getattr(settings, "IMAP_PASSWORD", "")
            or getattr(settings, "EMAIL_HOST_PASSWORD", "")
            or ""
        )
        mailbox = (
            options["mailbox"]
            or getattr(settings, "IMAP_MAILBOX", "")
            or "INBOX"
        )
        dry_run = bool(options["dry_run"])
        limit = max(1, int(options["limit"]))

        if not user or not password:
            raise CommandError(
                "Identifiants IMAP manquants. Ajoute dans .env :\n"
                "  EMAIL_HOST_PASSWORD=…   # ou IMAP_PASSWORD=…\n"
                "  EMAIL_HOST_USER=admin@jazz-orchestra-yonnais.fr  # si besoin\n"
                "Optionnel : IMAP_HOST=imap.hostinger.com IMAP_MAILBOX=INBOX"
            )

        try:
            client = imaplib.IMAP4_SSL(host, port)
            client.login(user, password)
        except imaplib.IMAP4.error as exc:
            raise CommandError(f"Connexion IMAP impossible : {exc}") from exc

        deleted = 0
        matched = 0
        scanned = 0
        try:
            typ, _ = client.select(mailbox, readonly=dry_run)
            if typ != "OK":
                raise CommandError(f"Ouverture mailbox {mailbox!r} échouée.")

            typ, data = client.search(None, "ALL")
            if typ != "OK" or not data or not data[0]:
                self.stdout.write("Aucun message.")
                return

            ids = data[0].split()
            # Plus récents d’abord
            ids = list(reversed(ids))[:limit]

            for msg_id in ids:
                scanned += 1
                typ, fetched = client.fetch(msg_id, "(RFC822)")
                if typ != "OK" or not fetched or not fetched[0]:
                    continue
                raw: Any = fetched[0]
                if not isinstance(raw, tuple) or len(raw) < 2:
                    continue
                msg = email.message_from_bytes(raw[1])
                subject, body = extract_text_from_message(msg)
                if not is_english_seo_spam(subject, body):
                    continue
                matched += 1
                preview = (subject or "(sans objet)")[:80]
                if dry_run:
                    self.stdout.write(f"[dry-run] {preview}")
                    continue
                # Suppression silencieuse : pas d’e-mail, pas de notif app
                client.store(msg_id, "+FLAGS", "\\Deleted")
                deleted += 1
                logger.info("SEO spam EN purgé IMAP id=%s subject=%r", msg_id, preview)
                self.stdout.write(f"supprimé: {preview}")

            if not dry_run and deleted:
                client.expunge()
        finally:
            try:
                client.logout()
            except Exception:
                pass

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"{matched} message(s) SEO EN sur {scanned} scanné(s) — rien effacé."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"{deleted} message(s) SEO EN effacé(s) "
                    f"({matched} match / {scanned} scannés)."
                )
            )
