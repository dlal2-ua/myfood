"""Colas de trabajos de iafood hacia el `worker` (sección 19: la llamada
real al proveedor de IA nunca corre en el hilo que atiende la petición del
usuario). Listas Redis simples con `BRPOP`, no una cola de propósito
general (Celery/RQ): pocos tipos de trabajo, y el volumen esperado (uso
personal/familiar) no lo justifica. Una cola por tipo de sesión (en vez de
una única cola con un campo "kind") para que el worker pueda escuchar cada
una con su propio bucle, sin tener que descartar mensajes de otro tipo.
"""

import json

import redis.asyncio as redis

from myfood.config import get_settings

DIET_PLAN_QUEUE_KEY = "iafood:jobs:diet_plan"
SMART_LOG_QUEUE_KEY = "iafood:jobs:smart_log"
RECIPE_IMPORT_QUEUE_KEY = "iafood:jobs:recipe_import"
RECEIPT_SCAN_QUEUE_KEY = "iafood:jobs:receipt_scan"
CHAT_QUEUE_KEY = "iafood:jobs:chat"

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


async def enqueue_receipt_scan_job(ai_session_id: str) -> None:
    await enqueue_job(RECEIPT_SCAN_QUEUE_KEY, ai_session_id)


async def dequeue_receipt_scan_job(timeout_seconds: int = 5) -> str | None:
    return await dequeue_job(RECEIPT_SCAN_QUEUE_KEY, timeout_seconds)


async def enqueue_chat_job(ai_session_id: str) -> None:
    await enqueue_job(CHAT_QUEUE_KEY, ai_session_id)


async def dequeue_chat_job(timeout_seconds: int = 5) -> str | None:
    return await dequeue_job(CHAT_QUEUE_KEY, timeout_seconds)


# --- Resultado síncrono del chat (sección 7.9/24.3) -------------------------
#
# El resto de iafood es 202 + polling de `ai_sessions` (regla 19: el
# proveedor de IA nunca se llama desde el hilo de la petición). El chat es
# la única excepción deliberada: la especificación lo diseña como una
# respuesta SÍNCRONA con su propio timeout de turno (sección 24.5, 20s) —
# tiene sentido para una conversación, no para pedir al usuario que haga
# polling de cada mensaje. Para no romper la regla 19 de todas formas, el
# proceso `api` sigue sin llamar nunca al Agent SDK: encola igual que
# cualquier otro flujo y solo espera el resultado con un `BRPOP` de Redis
# (operación local) hasta el timeout del turno — la llamada al modelo la hace
# el `worker`, exactamente igual que en el resto de iafood. (La nota de voz sí
# se transcribe en el proceso `api`, en memoria: ver `chat/flow.py`.)
def _chat_result_key(ai_session_id: str) -> str:
    return f"iafood:chat_result:{ai_session_id}"


async def push_chat_result(ai_session_id: str, payload: dict) -> None:
    key = _chat_result_key(ai_session_id)
    await _redis.lpush(key, json.dumps(payload))
    # Por si nadie llega a hacer BRPOP (p. ej. el cliente ya cortó la
    # conexión tras su propio timeout) — no debe quedar colgado para siempre.
    await _redis.expire(key, 60)


async def wait_for_chat_result(ai_session_id: str, timeout_seconds: int) -> dict | None:
    result = await _redis.brpop([_chat_result_key(ai_session_id)], timeout=timeout_seconds)
    if result is None:
        return None
    _key, raw = result
    return json.loads(raw)
