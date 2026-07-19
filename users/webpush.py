"""Envoi Web Push (VAPID) — couche basse."""

from __future__ import annotations

import json
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def vapid_configured() -> bool:
    return bool(
        getattr(settings, "VAPID_PRIVATE_KEY", "")
        and getattr(settings, "VAPID_PUBLIC_KEY", "")
    )


def vapid_public_key() -> str:
    return getattr(settings, "VAPID_PUBLIC_KEY", "") or ""


def send_web_push(subscription, *, title: str, body: str, url: str = "") -> bool:
    """
    Envoie une notification push à une subscription.

    Retourne True si OK. Supprime la subscription si l’endpoint est mort (410/404).
    """
    if not vapid_configured():
        logger.warning("Web Push ignoré : clés VAPID manquantes.")
        return False

    from pywebpush import WebPushException, webpush

    payload = json.dumps(
        {
            "title": title or "JOY",
            "body": body or "",
            "url": url or "/",
        },
        ensure_ascii=False,
    )
    claims = {
        "sub": f"mailto:{getattr(settings, 'VAPID_ADMIN_EMAIL', 'admin@jazz-orchestra-yonnais.fr')}"
    }
    private_key = settings.VAPID_PRIVATE_KEY
    if "\\n" in private_key and "-----BEGIN" in private_key:
        private_key = private_key.replace("\\n", "\n")

    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {
                    "p256dh": subscription.p256dh,
                    "auth": subscription.auth,
                },
            },
            data=payload,
            vapid_private_key=private_key,
            vapid_claims=claims,
            ttl=86400,
        )
        return True
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            logger.info(
                "Subscription push expirée (HTTP %s), suppression id=%s",
                status,
                subscription.pk,
            )
            subscription.delete()
        else:
            logger.warning(
                "Échec Web Push subscription_id=%s status=%s: %s",
                subscription.pk,
                status,
                exc,
            )
        return False
    except Exception:
        logger.exception(
            "Échec Web Push inattendu subscription_id=%s", subscription.pk
        )
        return False
