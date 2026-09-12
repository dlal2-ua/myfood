"""`ai/queue.py` usa `BRPOP` (bloqueante en el servidor) sobre el mismo
Redis compartido que usa el `worker` real desplegado — importante para
estos tests: un `dequeue_diet_plan_job` real aquí competiría con el
consumidor real del worker por cualquier trabajo que se encole (el worker
está continuamente bloqueado en `BRPOP` sobre la misma cola). Por eso el
"round trip" no se prueba con un dequeue real; se prueba el efecto de
`enqueue` con `LLEN`/`LREM` (no interfieren con `BRPOP`) y la lógica de
`dequeue` con el propio `brpop` simulado.

El cliente de redis-py necesita además `socket_timeout=None` (o mayor que
el propio timeout de `BRPOP`) para no cortar la lectura del socket antes
de que el servidor responda — se rompió en vivo tras el despliegue (el
bucle del worker fallaba en cada vuelta con `redis.exceptions.TimeoutError`,
no relacionado con "no había trabajos") porque redis-py 8.x pone
`socket_timeout=5` por defecto, exactamente el mismo valor que el timeout
de `BRPOP` que ya usaba este módulo."""

from myfood.ai.queue import (
    DIET_PLAN_QUEUE_KEY,
    SMART_LOG_QUEUE_KEY,
    _redis,
    dequeue_diet_plan_job,
    dequeue_smart_log_job,
    enqueue_diet_plan_job,
    enqueue_smart_log_job,
)


def test_redis_client_has_no_socket_timeout():
    assert _redis.connection_pool.connection_kwargs.get("socket_timeout") is None


async def test_enqueue_pushes_the_session_id_onto_the_queue(monkeypatch):
    # Se simula `lpush` en vez de comprobar el estado real de la cola: el
    # worker real puede estar bloqueado en `BRPOP` sobre esta misma cola en
    # este preciso instante, y serviría cualquier valor empujado antes de
    # que un `LLEN` posterior llegue a verlo — comprobado en vivo (ver
    # docstring del módulo), no es un caso hipotético.
    captured = {}

    async def _fake_lpush(key, value):
        captured["key"] = key
        captured["value"] = value

    monkeypatch.setattr(_redis, "lpush", _fake_lpush)

    await enqueue_diet_plan_job("test-session-id")

    assert captured == {"key": DIET_PLAN_QUEUE_KEY, "value": "test-session-id"}


async def test_dequeue_parses_a_real_brpop_result(monkeypatch):
    async def _fake_brpop(keys, timeout):
        assert keys == [DIET_PLAN_QUEUE_KEY]
        return (DIET_PLAN_QUEUE_KEY, "some-session-id")

    monkeypatch.setattr(_redis, "brpop", _fake_brpop)

    result = await dequeue_diet_plan_job(timeout_seconds=1)

    assert result == "some-session-id"


async def test_dequeue_returns_none_when_brpop_times_out(monkeypatch):
    async def _fake_brpop(keys, timeout):
        return None

    monkeypatch.setattr(_redis, "brpop", _fake_brpop)

    result = await dequeue_diet_plan_job(timeout_seconds=1)

    assert result is None


async def test_smart_log_queue_uses_its_own_key(monkeypatch):
    """Cada tipo de sesión tiene su propia cola — un trabajo de Smart Log
    no debe acabar en la cola de planes de dieta ni viceversa."""
    captured = {}

    async def _fake_lpush(key, value):
        captured["key"] = key
        captured["value"] = value

    monkeypatch.setattr(_redis, "lpush", _fake_lpush)

    await enqueue_smart_log_job("test-smart-log-id")

    assert captured == {"key": SMART_LOG_QUEUE_KEY, "value": "test-smart-log-id"}
    assert SMART_LOG_QUEUE_KEY != DIET_PLAN_QUEUE_KEY


async def test_dequeue_smart_log_parses_a_real_brpop_result(monkeypatch):
    async def _fake_brpop(keys, timeout):
        assert keys == [SMART_LOG_QUEUE_KEY]
        return (SMART_LOG_QUEUE_KEY, "some-smart-log-id")

    monkeypatch.setattr(_redis, "brpop", _fake_brpop)

    result = await dequeue_smart_log_job(timeout_seconds=1)

    assert result == "some-smart-log-id"
