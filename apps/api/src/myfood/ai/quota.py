"""Cuotas de uso de iafood (sección 10.1) — contadas en Redis con clave
`iafood:quota:{user_id}:{YYYY-MM-DD}` y `iafood:quota:instance:{YYYY-MM-DD}`,
TTL hasta medianoche. La especificación dice "zona horaria del perfil"; el
esquema actual no guarda una zona horaria por usuario (solo `users.timezone`,
sin usar todavía en ningún otro sitio), así que se usa `settings.tz` (la de
la instancia) — sería la zona horaria de todos los perfiles reales de esta
instancia en la práctica (uso familiar en un único hogar).
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import redis.asyncio as redis

from myfood.ai.limits import load_limits
from myfood.config import get_settings

_redis = redis.from_url(get_settings().redis_url, decode_responses=True)


class QuotaExceeded(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _today_and_ttl() -> tuple[str, int]:
    now = datetime.now(ZoneInfo(get_settings().tz))
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return now.date().isoformat(), int((midnight - now).total_seconds())


async def _incr_and_check(key: str, ttl: int, limit: int, error_code: str, message: str) -> None:
    count = await _redis.incr(key)
    if count == 1:
        await _redis.expire(key, ttl)
    if count > limit:
        raise QuotaExceeded(error_code, message)


async def check_and_consume_quota(
    user_id: UUID,
    *,
    scope: str = "diet_plan",
    per_profile_limit: int | None = None,
    enforce_instance: bool = True,
) -> None:
    """Se llama justo antes de encolar el trabajo para el `worker`. Si el
    perfil ya agotó su cuota, ni siquiera se comprueba la de instancia — el
    intento no llega a "gastar" cuota compartida por algo que de todas
    formas se iba a rechazar.

    `scope` separa la cuota por funcionalidad (mismo criterio que la
    sección 24.5 para el chat: "cuota propia, separada de la generación de
    dietas") — Smart Log puede usarse muchas veces al día para registrar
    rápido, un patrón de uso muy distinto al de generar un plan completo,
    así que comparten los mismos límites configurados pero no el mismo
    contador. `per_profile_limit`, si se pasa, sustituye
    `limits.per_profile_daily` — el chat (sección 24.5) tiene su propio
    número configurable (`chatMessagesPerProfileDaily`), distinto del de
    generación de dietas. `enforce_instance=False` omite el tope de
    instancia: la sección 24.5 solo define un límite POR PERFIL para el chat
    (50/día), y aplicarle el `instance_daily` de la generación de dietas (30)
    lo dejaba incoherente — nadie podía llegar a sus 50 mensajes, y la suma de
    toda la casa se agotaba con 30 (encontrado en la primera prueba real)."""
    limits = load_limits()
    today, ttl = _today_and_ttl()

    await _incr_and_check(
        f"iafood:quota:{scope}:{user_id}:{today}",
        ttl,
        per_profile_limit if per_profile_limit is not None else limits.per_profile_daily,
        "AI_QUOTA_PROFILE",
        "Has alcanzado tu límite diario de generaciones con IA.",
    )
    if not enforce_instance:
        return
    await _incr_and_check(
        f"iafood:quota:{scope}:instance:{today}",
        ttl,
        limits.instance_daily,
        "AI_QUOTA_INSTANCE",
        "Se ha alcanzado el límite diario de generaciones con IA de esta instancia.",
    )


async def quota_status(user_id: UUID, *, scope: str, per_profile_limit: int | None = None,
                       enforce_instance: bool = True) -> dict:
    """Cuánta cuota le queda al usuario HOY en `scope`, sin gastar ninguna.

    Lee los mismos contadores que `check_and_consume_quota` incrementa, así que el número
    que ve el usuario antes de pulsar es exactamente el que se va a comprobar. Existe
    porque la cuota se gasta al ENCOLAR: cada pulsación cuenta aunque el resultado no
    llegue, y sin enseñarlo por pantalla la única forma de enterarse era quedarse sin
    peticiones (encontrado en producción: cuatro pulsaciones seguidas del mismo texto)."""
    limits = load_limits()
    today, _ttl = _today_and_ttl()
    profile_limit = (
        per_profile_limit if per_profile_limit is not None else limits.per_profile_daily
    )
    used = int(await _redis.get(f"iafood:quota:{scope}:{user_id}:{today}") or 0)
    status = {
        "scope": scope,
        "used": min(used, profile_limit),
        "limit": profile_limit,
        "remaining": max(0, profile_limit - used),
        "reset_at": reset_at_iso(),
        "instance_limit": None,
        "instance_remaining": None,
    }
    if enforce_instance:
        instance_used = int(await _redis.get(f"iafood:quota:{scope}:instance:{today}") or 0)
        status["instance_limit"] = limits.instance_daily
        status["instance_remaining"] = max(0, limits.instance_daily - instance_used)
        status["remaining"] = min(status["remaining"], status["instance_remaining"])
    return status


def reset_at_iso() -> str:
    now = datetime.now(ZoneInfo(get_settings().tz))
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(UTC).isoformat()
