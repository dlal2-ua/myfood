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


async def check_and_consume_quota(user_id: UUID) -> None:
    """Se llama justo antes de encolar el trabajo para el `worker`. Si el
    perfil ya agotó su cuota, ni siquiera se comprueba la de instancia — el
    intento no llega a "gastar" cuota compartida por algo que de todas
    formas se iba a rechazar."""
    limits = load_limits()
    today, ttl = _today_and_ttl()

    await _incr_and_check(
        f"iafood:quota:{user_id}:{today}",
        ttl,
        limits.per_profile_daily,
        "AI_QUOTA_PROFILE",
        "Has alcanzado tu límite diario de generaciones con IA.",
    )
    await _incr_and_check(
        f"iafood:quota:instance:{today}",
        ttl,
        limits.instance_daily,
        "AI_QUOTA_INSTANCE",
        "Se ha alcanzado el límite diario de generaciones con IA de esta instancia.",
    )


def reset_at_iso() -> str:
    now = datetime.now(ZoneInfo(get_settings().tz))
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(UTC).isoformat()
