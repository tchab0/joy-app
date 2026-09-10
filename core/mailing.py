"""Envoi d’e-mails staff (SMTP réel, personnalisation {{prenom}})."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from email.utils import parseaddr
from typing import Iterable

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email

from .models import StaffMailing

logger = logging.getLogger(__name__)

User = get_user_model()

PRENOM_TOKEN = "{{prenom}}"
DEFAULT_BODY = f"Bonjour {PRENOM_TOKEN},\n\n"
SKIP_EMAIL_SUFFIXES = (".fake.net", "@fake.net")
_BONJOUR_EMPTY_RE = re.compile(r"Bonjour\s+,", re.IGNORECASE)


@dataclass(frozen=True)
class MailRecipient:
    email: str
    prenom: str = ""
    user_id: int | None = None

    def as_dict(self) -> dict:
        return {
            "email": self.email,
            "prenom": self.prenom,
            "user_id": self.user_id,
        }


def is_skipped_email(email: str) -> bool:
    e = (email or "").strip().lower()
    return any(e.endswith(suf) for suf in SKIP_EMAIL_SUFFIXES)


def musician_display_name(user) -> str:
    first = (getattr(user, "first_name", "") or "").strip()
    last = (getattr(user, "last_name", "") or "").strip()
    if first and last:
        return f"{first} {last}"
    if first:
        return first
    return (getattr(user, "username", "") or "").strip() or "—"


def musician_prenom(user) -> str:
    first = (getattr(user, "first_name", "") or "").strip()
    if first:
        return first
    return (getattr(user, "username", "") or "").strip()


def active_musicians_qs(*, include_fake: bool = False):
    qs = (
        User.objects.filter(is_musician=True, is_active=True)
        .exclude(email="")
        .order_by("last_name", "first_name", "username")
    )
    if include_fake:
        return qs
    # Filtre Python pour suffixes ; la plupart des comptes ont un vrai domaine.
    return qs


def list_musician_choices(*, include_fake: bool = False) -> list[User]:
    users = list(active_musicians_qs(include_fake=include_fake))
    if include_fake:
        return users
    return [u for u in users if not is_skipped_email(u.email or "")]


def personalize(template: str, prenom: str) -> str:
    """Remplace ``{{prenom}}`` ; si vide, normalise « Bonjour , » → « Bonjour, »."""
    prenom = (prenom or "").strip()
    text = (template or "").replace(PRENOM_TOKEN, prenom)
    if not prenom:
        text = _BONJOUR_EMPTY_RE.sub("Bonjour,", text)
        text = re.sub(r" {2,}", " ", text)
        text = "\n".join(line.rstrip() for line in text.split("\n"))
    return text


def parse_free_emails(raw: str) -> list[str]:
    """Parse adresses libres (virgules / espaces / retours ligne)."""
    if not raw or not str(raw).strip():
        return []
    parts = re.split(r"[\s,;]+", str(raw).strip())
    emails: list[str] = []
    seen: set[str] = set()
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # Accepte "Nom <addr@x.fr>"
        _name, addr = parseaddr(part)
        addr = (addr or part).strip().lower()
        if not addr:
            continue
        try:
            validate_email(addr)
        except ValidationError as exc:
            raise ValidationError(f"Adresse e-mail invalide : {part}") from exc
        if addr in seen:
            continue
        seen.add(addr)
        emails.append(addr)
    return emails


def resolve_recipients(
    *,
    musician_ids: Iterable[int],
    free_emails_raw: str = "",
    include_fake: bool = False,
) -> list[MailRecipient]:
    """Construit la liste dédupliquée (musiciens sélectionnés + adresses libres)."""
    ids = []
    seen_ids: set[int] = set()
    for raw_id in musician_ids or []:
        try:
            pk = int(raw_id)
        except (TypeError, ValueError):
            continue
        if pk in seen_ids:
            continue
        seen_ids.add(pk)
        ids.append(pk)

    recipients: list[MailRecipient] = []
    seen_emails: set[str] = set()

    if ids:
        users = User.objects.filter(
            pk__in=ids,
            is_musician=True,
            is_active=True,
        ).exclude(email="")
        by_id = {u.pk: u for u in users}
        for pk in ids:
            user = by_id.get(pk)
            if not user:
                continue
            email = (user.email or "").strip().lower()
            if not email:
                continue
            if not include_fake and is_skipped_email(email):
                continue
            if email in seen_emails:
                continue
            seen_emails.add(email)
            recipients.append(
                MailRecipient(
                    email=email,
                    prenom=musician_prenom(user),
                    user_id=user.pk,
                )
            )

    for email in parse_free_emails(free_emails_raw):
        if not include_fake and is_skipped_email(email):
            continue
        if email in seen_emails:
            continue
        seen_emails.add(email)
        recipients.append(MailRecipient(email=email, prenom="", user_id=None))

    return recipients


def send_staff_mailing(
    *,
    sent_by,
    subject: str,
    body_template: str,
    recipients: list[MailRecipient],
) -> StaffMailing:
    """Envoie 1 mail par destinataire et enregistre le journal."""
    subject = (subject or "").strip()
    body_template = body_template or ""
    if not subject:
        raise ValidationError("Le sujet est obligatoire.")
    if not body_template.strip():
        raise ValidationError("Le message est obligatoire.")
    if not recipients:
        raise ValidationError("Aucun destinataire.")
    if not getattr(settings, "EMAIL_SENDING_ENABLED", True):
        raise ValidationError(
            "Envoi e-mail temporairement désactivé. Réessayez plus tard."
        )

    results: list[dict] = []
    sent_count = 0
    failed_count = 0

    for recip in recipients:
        personalized_subject = personalize(subject, recip.prenom)
        personalized_body = personalize(body_template, recip.prenom)
        entry = recip.as_dict()
        try:
            send_mail(
                subject=personalized_subject,
                message=personalized_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recip.email],
                fail_silently=False,
            )
            entry["status"] = "sent"
            sent_count += 1
        except Exception as exc:
            logger.exception("Échec envoi staff mail à %s", recip.email)
            entry["status"] = "failed"
            entry["error"] = str(exc)[:500]
            failed_count += 1
        results.append(entry)

    return StaffMailing.objects.create(
        sent_by=sent_by if getattr(sent_by, "pk", None) else None,
        subject=subject,
        body_template=body_template,
        recipients=results,
        sent_count=sent_count,
        failed_count=failed_count,
    )
