"""Colas de trabajos de iafood hacia el `worker` (sección 19: la llamada
real al proveedor de IA nunca corre en el hilo que atiende la petición del
usuario). Listas Redis simples con `BRPOP`, no una cola de propósito
general (Celery/RQ): pocos tipos de trabajo, y el volumen esperado (uso
personal/familiar) no lo justifica. Una cola por tipo de sesión (en vez de
una única cola con un campo "kind") para que el worker pueda escuchar cada
una con su propio bucle, sin tener que descartar mensajes de otro tipo.
"""

import redis.asyncio as redis

from myfood.config import get_settings

DIET_PLAN_QUEUE_KEY = "iafood:jobs:diet_plan"
SMART_LOG_QUEUE_KEY = "iafood:jobs:smart_log"
RECIPE_IMPORT_QUEUE_KEY = "iafood:jobs:recipe_import"

# `socket_timeout` explícito a `None`: redis-py (desde 8.x) pone un
# `socket_timeout=5` por defecto en el cliente async, que compite con el
# propio timeout de `BRPOP` (bloqueante en el servidor) — con ambos en 5s,
# el cliente puede cortar la lectura del socket antes de que el propio
# BRPOP termine su espera, lanzando un `redis.exceptions.TimeoutError` que
# no tiene nada que ver con "no había trabajos" (encontrado en vivo:
# el bucle del worker fallaba en cada vuelta con ese error). `BRPOP` ya
# tiene su propio parámetro de timeout — el socket debe esperar más que
# eso, no menos.
_redis = redis.from_url(get_settings().redis_url, decode_responses=True, socket_timeout=None)


async def enqueue_job(queue_key: str, ai_session_id: str) -> None:
    await _redis.lpush(queue_key, ai_session_id)


async def dequeue_job(queue_key: str, timeout_seconds: int = 5) -> str | None:
    """Bloquea hasta `timeout_seconds` esperando un trabajo en `queue_key`
    — deja al worker comprobar otras colas/tareas entre esperas en vez de
    quedarse bloqueado indefinidamente."""
    result = await _redis.brpop([queue_key], timeout=timeout_seconds)
    if result is None:
        return None
    _key, ai_session_id = result
    return ai_session_id


async def enqueue_diet_plan_job(ai_session_id: str) -> None:
    await enqueue_job(DIET_PLAN_QUEUE_KEY, ai_session_id)


async def dequeue_diet_plan_job(timeout_seconds: int = 5) -> str | None:
    return await dequeue_job(DIET_PLAN_QUEUE_KEY, timeout_seconds)


async def enqueue_smart_log_job(ai_session_id: str) -> None:
    await enqueue_job(SMART_LOG_QUEUE_KEY, ai_session_id)


async def dequeue_smart_log_job(timeout_seconds: int = 5) -> str | None:
    return await dequeue_job(SMART_LOG_QUEUE_KEY, timeout_seconds)


async def enqueue_recipe_import_job(ai_session_id: str) -> None:
    await enqueue_job(RECIPE_IMPORT_QUEUE_KEY, ai_session_id)


async def dequeue_recipe_import_job(timeout_seconds: int = 5) -> str | None:
    return await dequeue_job(RECIPE_IMPORT_QUEUE_KEY, timeout_seconds)
