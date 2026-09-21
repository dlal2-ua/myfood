"""Worker de tareas de fondo (sección 19) — nunca corre en el hilo que
atiende la petición del usuario. Desde la Fase 3: bucle de recordatorios
push (agua/suplementos) según `notification_rules`. Desde la Fase 5: cola
de trabajos de iafood (sección 10.6) — la única llamada real al Claude
Agent SDK de todo el proyecto corre aquí, nunca en el proceso `api`.
"""

import asyncio
import logging
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import redis.asyncio as redis
from sqlalchemy import select, update

from myfood.ai.flows.diet_plan import process_diet_plan_job
from myfood.ai.flows.receipt_scan import process_receipt_scan_job
from myfood.ai.flows.recipe_import import process_recipe_import_job
from myfood.ai.flows.smart_log import process_smart_log_job
from myfood.ai.flows.supplement_suggestion import process_supplement_suggestion_job
from myfood.ai.queue import (
    dequeue_chat_job,
    dequeue_diet_plan_job,
    dequeue_job,
    dequeue_receipt_scan_job,
    dequeue_recipe_import_job,
    dequeue_smart_log_job,
    dequeue_supplement_suggestion_job,
)
from myfood.chat.flow import process_chat_job
from myfood.config import get_settings
from myfood.db.models import (
    AiSession,
    NotificationRule,
    PushSubscription,
    User,
    UserAchievement,
)
from myfood.db.session import AdminSessionLocal
from myfood.domain.achievements import collect_counters, sync_achievements
from myfood.domain.gamification import achievement_title, build_achievements
from myfood.notification_content import (
    achievement_notification,
    build_notification,
    low_stock_notifications,
)
from myfood.notifications import is_rule_due
from myfood.push import PushSubscriptionExpired, send_push
from myfood.services.images import IMAGE_JOBS_QUEUE_KEY, process_image_job, purge_cache

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


def _zone(timezone: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(timezone or settings.tz)
    except ZoneInfoNotFoundError:
        return ZoneInfo(settings.tz)


_LOW_STOCK_HOUR = time(10, 0)
_LOW_STOCK_TOLERANCE_MINUTES = 2


async def _send_to_user(session, user_id, payload: dict) -> int:
    """Envía `payload` a todas las suscripciones del usuario; borra las caducadas."""
    sent = 0
    subs = list(
        await session.scalars(select(PushSubscription).where(PushSubscription.user_id == user_id))
    )
    for sub in subs:
        try:
            send_push(sub, payload)
            sent += 1
        except PushSubscriptionExpired:
            await session.delete(sub)
        except Exception:
            # Un fallo de red/servicio de push de UN suscriptor no debe bloquear el envío a los
            # demás ni al resto de reglas de este mismo tick.
            logger.exception("fallo enviando push a %s", sub.endpoint)
    return sent


async def run_tick(now: datetime) -> int:
    """Un ciclo del bucle: revisa todas las reglas activas de todos los usuarios (sesión admin —
    sin contexto de un usuario concreto, igual justificación que `/admin/*`, sección 22) y envía
    lo que toque, evaluando cada regla en la zona horaria de su dueño. `now` es un instante con
    zona (UTC en producción). Devuelve cuántas notificaciones se enviaron (logging/tests)."""
    if now.tzinfo is None:
        raise ValueError("run_tick necesita un datetime con zona horaria")
    sent = 0
    async with AdminSessionLocal() as session:
        rules = list(
            await session.scalars(
                select(NotificationRule).where(NotificationRule.is_enabled.is_(True))
            )
        )
        timezones = dict((await session.execute(select(User.id, User.timezone))).all())
        for rule in rules:
            local_now = now.astimezone(_zone(timezones.get(rule.user_id)))
            due, slot = is_rule_due(rule, local_now)
            if not due or await _already_sent(rule.id, local_now.date().isoformat(), slot):
                continue
            payload = await build_notification(session, rule, local_now)
            if payload is None:
                continue
            sent += await _send_to_user(session, rule.user_id, payload)

        # Stock bajo: un aviso al día por suplemento, a las 10:00 hora del usuario.
        for user_id, supplement_id, payload in await low_stock_notifications(session):
            local_now = now.astimezone(_zone(timezones.get(user_id)))
            minutes = local_now.hour * 60 + local_now.minute
            slot_minutes = _LOW_STOCK_HOUR.hour * 60 + _LOW_STOCK_HOUR.minute
            if abs(minutes - slot_minutes) > _LOW_STOCK_TOLERANCE_MINUTES:
                continue
            if await _already_sent(
                f"lowstock-{supplement_id}", local_now.date().isoformat(), _LOW_STOCK_HOUR
            ):
                continue
            sent += await _send_to_user(session, user_id, payload)
        await session.commit()
    return sent


_AI_QUEUE_POLL_TIMEOUT_SECONDS = 5


async def _notifications_loop() -> None:
    while True:
        try:
            sent = await run_tick(datetime.now(UTC))
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


async def _supplement_suggestion_jobs_loop() -> None:
    while True:
        try:
            ai_session_id = await dequeue_supplement_suggestion_job(_AI_QUEUE_POLL_TIMEOUT_SECONDS)
            if ai_session_id is None:
                continue
            await process_supplement_suggestion_job(ai_session_id)
        except Exception:
            logger.exception("fallo procesando una sugerencia de suplementos — se sigue")


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


async def _receipt_scan_jobs_loop() -> None:
    while True:
        try:
            ai_session_id = await dequeue_receipt_scan_job(_AI_QUEUE_POLL_TIMEOUT_SECONDS)
            if ai_session_id is None:
                continue
            await process_receipt_scan_job(ai_session_id)
        except Exception:
            logger.exception(
                "fallo procesando un trabajo de escaneo de ticket — se reintenta con el siguiente"
            )


async def _chat_jobs_loop() -> None:
    while True:
        try:
            ai_session_id = await dequeue_chat_job(_AI_QUEUE_POLL_TIMEOUT_SECONDS)
            if ai_session_id is None:
                continue
            await process_chat_job(ai_session_id)
        except Exception:
            logger.exception("fallo procesando un trabajo de chat — se reintenta con el siguiente")


# Una sesión de iafood que sigue `running` pasado este tiempo ya no la va a
# terminar nadie (p. ej. el worker se reinició a mitad de un trabajo): el
# cliente que hace polling se quedaría esperando para siempre. El peor caso
# legítimo de un trabajo es el plan de dieta (2 intentos de 60 s).
_STALE_SESSION_AFTER = timedelta(minutes=10)
_STALE_SWEEP_SECONDS = 300


async def fail_stale_sessions(now: datetime | None = None) -> int:
    cutoff = (now or datetime.now(UTC)) - _STALE_SESSION_AFTER
    async with AdminSessionLocal() as session:
        result = await session.execute(
            update(AiSession)
            .where(AiSession.status == "running", AiSession.created_at < cutoff)
            .values(
                status="failed",
                validation_errors=[
                    {
                        "code": "SESSION_ORPHANED",
                        "message": "El trabajo no llegó a terminar (el servicio se reinició).",
                    }
                ],
            )
        )
        await session.commit()
        return result.rowcount


async def _stale_sessions_loop() -> None:
    while True:
        try:
            failed = await fail_stale_sessions()
            if failed:
                logger.warning("marcadas %s sesiones de iafood huérfanas como fallidas", failed)
        except Exception:
            logger.exception(
                "fallo limpiando sesiones huérfanas — se reintenta en el siguiente ciclo"
            )
        await asyncio.sleep(_STALE_SWEEP_SECONDS)


# OFF tarda ~10 s por imagen: varios consumidores para que una página de resultados no tarde.
_IMAGE_DOWNLOAD_WORKERS = 4


async def _image_jobs_loop() -> None:
    """Reintenta las descargas de imágenes que fallaron en la petición del usuario."""
    while True:
        try:
            payload = await dequeue_job(IMAGE_JOBS_QUEUE_KEY, _AI_QUEUE_POLL_TIMEOUT_SECONDS)
            if payload is None:
                continue
            await process_image_job(payload)
        except Exception:
            logger.exception("fallo descargando una imagen — se sigue con la siguiente")


_ACHIEVEMENTS_SWEEP_SECONDS = 15 * 60


async def sweep_achievements(today: date | None = None) -> int:
    """Detecta logros recién conseguidos y avisa una sola vez. Devuelve cuántos avisó.

    Corre aquí y no al registrar una comida porque un logro puede cumplirse sin que el
    usuario abra la app (p. ej. la racha la completa el último registro del día) y porque
    enviar el push es una llamada de red, que nunca debe colgar de la petición del usuario
    (regla 19). Entrar en «Progreso» también crea la fila del logro (para celebrarlo al
    momento), pero es este barrido el que manda el aviso, mirando `notified_at`.

    `notified_at` se marca aunque no haya a quién enviar (nadie suscrito a push): un logro
    de hace meses no debe aparecer de golpe el día que alguien active las notificaciones."""
    day = today or date.today()
    notified = 0
    async with AdminSessionLocal() as session:
        user_ids = list(await session.scalars(select(User.id).where(User.is_active.is_(True))))
        for user_id in user_ids:
            counters, _current, _longest = await collect_counters(session, user_id, today=day)
            await sync_achievements(session, user_id, build_achievements(**counters), today=day)

            pending = list(
                await session.scalars(
                    select(UserAchievement).where(
                        UserAchievement.user_id == user_id,
                        UserAchievement.notified_at.is_(None),
                    )
                )
            )
            for row in pending:
                title = achievement_title(row.key)
                if title is not None:
                    await _send_to_user(session, user_id, achievement_notification(title))
                    notified += 1
                row.notified_at = datetime.now(UTC)
            if pending:
                await session.commit()
    return notified


async def _achievements_loop() -> None:
    while True:
        try:
            notified = await sweep_achievements()
            if notified:
                logger.info("avisados %s logros nuevos", notified)
        except Exception:
            logger.exception("fallo revisando los logros — se reintenta en el siguiente ciclo")
        await asyncio.sleep(_ACHIEVEMENTS_SWEEP_SECONDS)


_IMAGE_PURGE_SECONDS = 6 * 60 * 60


async def _image_purge_loop() -> None:
    """Purga LRU de la caché de imágenes cuando supera `IMAGE_CACHE_BUDGET_GB` (sección 12)."""
    budget_bytes = settings.image_cache_budget_gb * 1024**3
    while True:
        try:
            async with AdminSessionLocal() as session:
                purged = await purge_cache(session, budget_bytes)
            if purged:
                logger.info("caché de imágenes: purgadas %s (LRU)", purged)
        except Exception:
            logger.exception("fallo purgando la caché de imágenes — se reintenta")
        await asyncio.sleep(_IMAGE_PURGE_SECONDS)


async def main() -> None:
    logger.info("MyFood worker arrancado — recordatorios cada %ss + colas de iafood", _TICK_SECONDS)
    await asyncio.gather(
        _notifications_loop(),
        _diet_plan_jobs_loop(),
        _smart_log_jobs_loop(),
        _supplement_suggestion_jobs_loop(),
        _recipe_import_jobs_loop(),
        _receipt_scan_jobs_loop(),
        _chat_jobs_loop(),
        _stale_sessions_loop(),
        _achievements_loop(),
        *(_image_jobs_loop() for _ in range(_IMAGE_DOWNLOAD_WORKERS)),
        _image_purge_loop(),
    )


if __name__ == "__main__":
    asyncio.run(main())
