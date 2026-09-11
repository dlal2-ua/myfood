"""Caché Redis genérica de la API (sección 11.2 — evitar salir a APIs en vivo
más de lo necesario). Mismo patrón de cliente módulo-nivel que `security.py`.
"""

import json

import redis.asyncio as redis

from myfood.config import get_settings

settings = get_settings()
_redis = redis.from_url(settings.redis_url, decode_responses=True)

_BARCODE_KEY_PREFIX = "off:barcode:"
_BARCODE_TTL_SECONDS = 24 * 60 * 60  # 24h — un código sin datos hoy puede tenerlos mañana


async def get_cached_barcode_lookup(ean: str) -> dict | None:
    """`None` = sin entrada en caché (hay que consultar OFF). Una entrada en
    caché puede ser `{"found": False}` (negativo cacheado, sección 11.2 —
    evita repetir la llamada en vivo a OFF por cada escaneo del mismo código
    no encontrado) o `{"found": True, ...datos...}`."""
    raw = await _redis.get(f"{_BARCODE_KEY_PREFIX}{ean}")
    if raw is None:
        return None
    return json.loads(raw)


async def set_cached_barcode_lookup(ean: str, value: dict) -> None:
    await _redis.set(
        f"{_BARCODE_KEY_PREFIX}{ean}", json.dumps(value), ex=_BARCODE_TTL_SECONDS
    )
