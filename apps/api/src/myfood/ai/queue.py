"""Cola de trabajos de iafood hacia el `worker` (sección 19: la llamada real
al proveedor de IA nunca corre en el hilo que atiende la petición del
usuario). Una lista Redis simple con `BRPOP`, no una cola de propósito
general (Celery/RQ): un solo tipo de trabajo por ahora, y el volumen
esperado (uso personal/familiar) no lo justifica.
"""

import redis.asyncio as redis

from myfood.config import get_settings

DIET_PLAN_QUEUE_KEY = "iafood:jobs:diet_plan"

_redis = redis.from_url(get_settings().redis_url, decode_responses=True)


async def enqueue_diet_plan_job(ai_session_id: str) -> None:
    await _redis.lpush(DIET_PLAN_QUEUE_KEY, ai_session_id)


async def dequeue_diet_plan_job(timeout_seconds: int = 5) -> str | None:
    """Bloquea hasta `timeout_seconds` esperando un trabajo — deja al
    worker comprobar otras tareas (recordatorios) entre esperas en vez de
    quedarse bloqueado indefinidamente."""
    result = await _redis.brpop([DIET_PLAN_QUEUE_KEY], timeout=timeout_seconds)
    if result is None:
        return None
    _key, ai_session_id = result
    return ai_session_id
