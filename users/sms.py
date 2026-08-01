"""Envoi de codes OTP par téléphone (console en dev, HTTP générique en prod)."""

from __future__ import annotations

import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)


def send_sms(to: str, body: str) -> None:
    backend = getattr(settings, "SMS_BACKEND", "console")
    if backend == "console":
        logger.info("Notification OTP → %s : %s", to, body)
        print(f"[OTP console] to={to} body={body}")
        return

    if backend == "http":
        _send_http(to, body)
        return

    raise RuntimeError(f"SMS_BACKEND inconnu : {backend}")


def _send_http(to: str, body: str) -> None:
    url = getattr(settings, "SMS_HTTP_URL", "")
    if not url:
        raise RuntimeError("SMS_HTTP_URL non configuré.")

    method = getattr(settings, "SMS_HTTP_METHOD", "POST").upper()
    to_field = getattr(settings, "SMS_HTTP_TO_FIELD", "to")
    body_field = getattr(settings, "SMS_HTTP_BODY_FIELD", "message")
    api_key = getattr(settings, "SMS_HTTP_API_KEY", "")
    api_key_header = getattr(settings, "SMS_HTTP_API_KEY_HEADER", "Authorization")

    payload = urllib.parse.urlencode({to_field: to, body_field: body}).encode()
    req = urllib.request.Request(url, data=payload, method=method)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    if api_key:
        req.add_header(api_key_header, api_key)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"OTP HTTP {resp.status}")
    except urllib.error.URLError as exc:
        logger.exception("Échec envoi notification OTP vers %s", to)
        raise RuntimeError("Échec d’envoi de notification") from exc
