"""Détection spam SEO anglophone (IMAP) et messages contact hors français."""

from __future__ import annotations

import re
from email.message import Message


_SEO_RE = re.compile(r"\bseo\b", re.IGNORECASE)

# Lettres hors alphabet latin (spam / messages non FR évidents).
_NON_LATIN_LETTER_RE = re.compile(
    "["
    "\u0400-\u04FF"  # cyrillique
    "\u0600-\u06FF"  # arabe
    "\u4E00-\u9FFF"  # CJK
    "\u3040-\u30FF"  # hiragana / katakana
    "\uAC00-\uD7AF"  # hangul
    "]"
)

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
    " bonsoir",
    " cordialement",
    " merci",
    " association",
    " concert",
    " prestation",
    " orchestre",
    " mariage",
    " disponible",
    " disponibilité",
    " demande",
    "vendée",
    "bonjour,",
    "bonsoir,",
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
    " looking for ",
    " available ",
    " wedding ",
    " please ",
)


def _normalize(text: str) -> str:
    return " " + re.sub(r"\s+", " ", (text or "").lower()) + " "


def _french_score(blob: str) -> int:
    fr = sum(1 for m in _FR_MARKERS if m in blob)
    # Accents français typiques → pousse vers FR
    if re.search(r"[àâäéèêëïîôùûüçœæ]", blob):
        fr += 2
    return fr


def contains_seo(text: str) -> bool:
    return bool(_SEO_RE.search(text or ""))


def looks_english(text: str) -> bool:
    """Heuristique légère : score EN > score FR (et au moins un marqueur EN)."""
    blob = _normalize(text)
    if not blob.strip():
        return False
    en = sum(1 for m in _EN_MARKERS if m in blob)
    fr = _french_score(blob)
    return en > fr and en >= 2


def has_non_latin_script(text: str, *, min_chars: int = 6) -> bool:
    """True si le texte contient assez de lettres hors alphabet latin."""
    return len(_NON_LATIN_LETTER_RE.findall(text or "")) >= min_chars


def looks_french(text: str) -> bool:
    """Heuristique légère : assez de marqueurs / accents français."""
    blob = _normalize(text)
    if not blob.strip():
        return False
    return _french_score(blob) >= 2


def looks_foreign_language(text: str) -> bool:
    """True si le texte semble rédigé dans une langue autre que le français.

    Textes trop courts : non jugés (évite les faux positifs).
    """
    raw = (text or "").strip()
    if len(raw) < 12:
        return False
    if has_non_latin_script(raw):
        return True
    if looks_english(raw):
        return True
    # Latin non anglais mais sans signaux FR (ex. spam ES/DE générique long).
    if len(raw) >= 40 and not looks_french(raw):
        return True
    return False


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
