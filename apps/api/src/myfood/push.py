"""Envío de Web Push autoalojado con VAPID (sección 10, Fase 3) — sin
Firebase ni terceros, cifrado end-to-end vía `pywebpush` (RFC 8291/8292).
"""

import json
import logging

from pywebpush import WebPushException, webpush

from myfood.config import get_settings
from myfood.db.models import PushSubscription

logger = logging.getLogger("myfood.push")

settings = get_settings()


class PushSubscriptionExpired(Exception):
    """La suscripción ya no es válida (404/410 del servicio de push del
    navegador) — el llamador debe borrar la fila de `push_subscriptions`."""


def send_push(subscription: PushSubscription, payload: dict) -> None:
    """Envía una notificación a una única suscripción. Lanza
    `PushSubscriptionExpired` si el navegador la ha invalidado (el usuario
    desinstaló la PWA, borró datos del sitio, etc.) — nunca para el resto de
    envíos por una suscripción muerta."""
    subscription_info = {
        "endpoint": subscription.endpoint,
        "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
    }
    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
        )
    except WebPushException as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code in (404, 410):
            raise PushSubscriptionExpired from exc
        logger.warning("push a %s falló (status=%s): %s", subscription.endpoint, status_code, exc)
