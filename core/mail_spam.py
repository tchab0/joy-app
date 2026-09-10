"""Détection spam SEO anglophone (boîte mail IMAP)."""

from __future__ import annotations

import re
from email.message import Message

_SEO_RE = re.compile(r"\bseo\b", re.IGNORECASE)

# Marqueurs grossiers FR vs EN — suffisant pour séparer pitches SEO EN des mails FR.
_FR_MARKERS = (
    " le ",
    " la ",
    " les ",
    " des ",
    " une ",
    " un ",
    " pour ",
    " avec ",
    " votre ",
    " vous ",
    " nous ",
    " bonjour",
    " cordialement",
    " merci",
    " association",
    " concert",
    " prestation",
    "vendée",
    "bonjour,",
)
_EN_MARKERS = (
    " the ",
    " your ",
    " you ",
    " with ",
    " from ",
    " that ",
    " this ",
    " website",
    " rankings",
    " google",
    " proposal",
    " pricing",
    " leads",
    " interested",
    " hi,",
    " hello",
    " regards",
    "checked your",
    "increase your",
    "quality leads",
)


def _normalize(text: str) -> str:
    return " " + re.sub(r"\s+", " ", (text or "").lower()) + " "


def contains_seo(text: str) -> bool:
    return bool(_SEO_RE.search(text or ""))


def looks_english(text: str) -> bool:
    """Heuristique légère : score EN > score FR (et au moins un marqueur EN)."""
    blob = _normalize(text)
    if not blob.strip():
        return False
    en = sum(1 for m in _EN_MARKERS if m in blob)
    fr = sum(1 for m in _FR_MARKERS if m in blob)
    # Accents français typiques → pousse vers FR
    if re.search(r"[àâäéèêëïîôùûüçœæ]", blob):
        fr += 2
    return en > fr and en >= 2


def is_english_seo_spam(subject: str, body: str) -> bool:
    combined = f"{subject or ''}\n{body or ''}"
    return contains_seo(combined) and looks_english(combined)


def _decode_part_payload(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        raw = part.get_payload()
        return raw if isinstance(raw, str) else ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def extract_text_from_message(msg: Message) -> tuple[str, str]:
    """Retourne (subject, body_text) à partir d’un email.message.Message."""
    subject = msg.get("Subject", "") or ""
    # Décodage RFC2047 basique via email.header
    from email.header import decode_header, make_header

    try:
        subject = str(make_header(decode_header(subject)))
    except Exception:
        pass

    texts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            disp = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disp:
                continue
            if ctype in ("text/plain", "text/html"):
                texts.append(_decode_part_payload(part))
    else:
        texts.append(_decode_part_payload(msg))

    body = "\n".join(texts)
    # Strip balises HTML grossièrement pour le scoring langue
    body_plain = re.sub(r"<[^>]+>", " ", body)
    return subject, body_plain
