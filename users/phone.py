"""Normalisation légère des numéros FR / internationaux."""

from __future__ import annotations

import re


def normalize_phone(raw: str | None) -> str:
    if not raw:
        return ""
    digits = re.sub(r"[^\d+]", "", raw.strip())
    if not digits:
        return ""

    if digits.startswith("00"):
        digits = "+" + digits[2:]

    if digits.startswith("+"):
        return "+" + re.sub(r"\D", "", digits[1:])

    national = re.sub(r"\D", "", digits)
    if len(national) == 10 and national.startswith("0"):
        return "+33" + national[1:]
    if len(national) == 9:
        return "+33" + national
    return national


def mask_destination(value: str, channel: str) -> str:
    if not value:
        return ""
    if channel == "email":
        local, _, domain = value.partition("@")
        if not domain:
            return "***"
        keep = local[:2] if len(local) > 2 else local[:1]
        return f"{keep}***@{domain}"
    # phone
    digits = re.sub(r"\D", "", value)
    if len(digits) < 4:
        return "***"
    return f"***{digits[-4:]}"
