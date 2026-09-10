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
        # #region agent log
        try:
            import time as _t
            open("/srv/jazz-orchestra-yonnais/.cursor/debug-e044df.log","a").write(json.dumps({"sessionId":"e044df","hypothesisId":"C","location":"webpush.py:send_web_push","message":"vapid_missing","data":{"sub_id":getattr(subscription,"pk",None)},"timestamp":int(_t.time()*1000)})+"\n")
        except Exception:
            pass
        # #endregion
        return False

    from py_vapid import Vapid
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
    # pywebpush.from_string n’accepte que raw/DER — pas le PEM.
    private_key = settings.VAPID_PRIVATE_KEY.replace("\\n", "\n").strip()
    if "-----BEGIN" in private_key:
        vapid_key = Vapid.from_pem(private_key.encode("utf-8"))
    else:
        vapid_key = Vapid.from_string(private_key)

    ua = (getattr(subscription, "user_agent", None) or "")[:80]
    endpoint_host = ""
    try:
        endpoint_host = (subscription.endpoint or "").split("/")[2][:60]
    except Exception:
        endpoint_host = "?"

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
            vapid_private_key=vapid_key,
            vapid_claims=claims,
            ttl=86400,
        )
        # #region agent log
        try:
            import time as _t
            open("/srv/jazz-orchestra-yonnais/.cursor/debug-e044df.log","a").write(json.dumps({"sessionId":"e044df","hypothesisId":"A","location":"webpush.py:send_web_push","message":"push_ok","data":{"sub_id":subscription.pk,"user_id":getattr(subscription,"user_id",None),"ua":ua,"endpoint_host":endpoint_host,"title":(title or "")[:80]},"timestamp":int(_t.time()*1000)})+"\n")
        except Exception:
            pass
        # #endregion
        return True
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        # #region agent log
        try:
            import time as _t
            open("/srv/jazz-orchestra-yonnais/.cursor/debug-e044df.log","a").write(json.dumps({"sessionId":"e044df","hypothesisId":"A","location":"webpush.py:send_web_push","message":"push_webpush_exception","data":{"sub_id":subscription.pk,"user_id":getattr(subscription,"user_id",None),"ua":ua,"endpoint_host":endpoint_host,"status":status,"err":str(exc)[:200]},"timestamp":int(_t.time()*1000)})+"\n")
        except Exception:
            pass
        # #endregion
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
    except Exception as exc:
        # #region agent log
        try:
            import time as _t
            open("/srv/jazz-orchestra-yonnais/.cursor/debug-e044df.log","a").write(json.dumps({"sessionId":"e044df","hypothesisId":"A","location":"webpush.py:send_web_push","message":"push_unexpected_exception","data":{"sub_id":getattr(subscription,"pk",None),"err":str(exc)[:200]},"timestamp":int(_t.time()*1000)})+"\n")
        except Exception:
            pass
        # #endregion
        logger.exception(
            "Échec Web Push inattendu subscription_id=%s", subscription.pk
        )
        return False
