"""Worker de tareas de fondo (sección 19) — nunca corre en el hilo que
atiende la petición del usuario. Desde la Fase 3: bucle de recordatorios
push (agua/suplementos) según `notification_rules`. Desde la Fase 5: cola
de trabajos de iafood (sección 10.6) — la única llamada real al Claude
Agent SDK de todo el proyecto corre aquí, nunca en el proceso `api`.
"""

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import redis.asyncio as redis
from sqlalchemy import select

from myfood.ai.flows.diet_plan import process_diet_plan_job
from myfood.ai.flows.recipe_import import process_recipe_import_job
from myfood.ai.flows.smart_log import process_smart_log_job
from myfood.ai.queue import (
    dequeue_diet_plan_job,
    dequeue_recipe_import_job,
    dequeue_smart_log_job,
)
from myfood.config import get_settings
from myfood.db.models import NotificationRule, PushSubscription
from myfood.db.session import AdminSessionLocal
from myfood.notifications import is_rule_due, message_for_rule
from myfood.push import PushSubscriptionExpired, send_push

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("myfood.worker")

settings = get_settings()
_redis = redis.from_url(settings.redis_url, decode_responses=True)

_TICK_SECONDS = 60
_DEDUP_TTL_SECONDS = 26 * 60 * 60  # más de un día, cubre el margen de un tick tardío


async def _already_sent(rule_id, day: str, slot) -> bool:
    """`True` si ya se envió este horario exacto de esta regla hoy — usa
    SETNX (vía `set(..., nx=True)`) como marca atómica: solo el primer tick
    que reclama la clave la considera "no enviada todavía"."""
    key = f"notif-sent:{rule_id}:{day}:{slot.isoformat()}"
    claimed = await _redis.set(key, "1", nx=True, ex=_DEDUP_TTL_SECONDS)
    return not claimed


async def run_tick(now: datetime) -> int:
    """Un ciclo del bucle: revisa todas las reglas activas de todos los
    usuarios (sesión admin — sin contexto de un usuario concreto, igual
    justificación que `/admin/*`, sección 22) y envía lo que toque. Devuelve
    cuántas notificaciones se enviaron (solo para logging/tests)."""
    sent = 0
    async with AdminSessionLocal() as session:
        rules = await session.scalars(
            select(NotificationRule).where(NotificationRule.is_enabled.is_(True))
        )
        for rule in rules:
            due, slot = is_rule_due(rule, now)
            if not due or await _already_sent(rule.id, now.date().isoformat(), slot):
                continue

            subs = list(
                await session.scalars(
                    select(PushSubscription).where(PushSubscription.user_id == rule.user_id)
                )
            )
            payload = message_for_rule(rule)
            for sub in subs:
                try:
                    send_push(sub, payload)
                    sent += 1
                except PushSubscriptionExpired:
                    await session.delete(sub)
                except Exception:
                    # Un fallo de red/servicio de push de UN suscriptor no
                    # debe bloquear el envío a los demás ni al resto de
                    # reglas de este mismo tick (antes: cualquier excepción
                    # aquí abortaba todo el `run_tick`, incluido el commit
                    # de borrados de suscripciones ya caducadas).
                    logger.exception("fallo enviando push a %s", sub.endpoint)
        await session.commit()
    return sent


_AI_QUEUE_POLL_TIMEOUT_SECONDS = 5


async def _notifications_loop() -> None:
    tz = ZoneInfo(settings.tz)
    while True:
        try:
            sent = await run_tick(datetime.now(tz))
            if sent:
                logger.info("enviadas %s notificaciones", sent)
        except Exception:
            logger.exception("fallo en el tick del worker — se reintenta en el siguiente ciclo")
        await asyncio.sleep(_TICK_SECONDS)


async def _diet_plan_jobs_loop() -> None:
    """`BRPOP` con timeout corto: deja el bucle libre para volver a
    comprobar la cola sin quedarse bloqueado indefinidamente si nunca llega
    ningún trabajo (no hay nada más que hacer aquí, a diferencia del bucle
    de recordatorios que sí tiene un tick periódico propio)."""
    while True:
        try:
            ai_session_id = await dequeue_diet_plan_job(_AI_QUEUE_POLL_TIMEOUT_SECONDS)
            if ai_session_id is None:
                continue
            await process_diet_plan_job(ai_session_id)
        except Exception:
            logger.exception(
                "fallo procesando un trabajo de plan de dieta — se reintenta con el siguiente"
            )


async def _smart_log_jobs_loop() -> None:
    while True:
        try:
            ai_session_id = await dequeue_smart_log_job(_AI_QUEUE_POLL_TIMEOUT_SECONDS)
            if ai_session_id is None:
                continue
            await process_smart_log_job(ai_session_id)
        except Exception:
            logger.exception(
                "fallo procesando un trabajo de Smart Log — se reintenta con el siguiente"
            )


async def _recipe_import_jobs_loop() -> None:
    while True:
        try:
            ai_session_id = await dequeue_recipe_import_job(_AI_QUEUE_POLL_TIMEOUT_SECONDS)
            if ai_session_id is None:
                continue
            await process_recipe_import_job(ai_session_id)
        except Exception:
            logger.exception(
                "fallo procesando un trabajo de importación de receta — se reintenta "
                "con el siguiente"
            )


async def main() -> None:
    logger.info(
        "MyFood worker arrancado — recordatorios cada %ss + colas de iafood", _TICK_SECONDS
    )
    await asyncio.gather(
        _notifications_loop(),
        _diet_plan_jobs_loop(),
        _smart_log_jobs_loop(),
        _recipe_import_jobs_loop(),
    )


if __name__ == "__main__":
    asyncio.run(main())
