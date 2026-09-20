"""Límite de intentos fallidos (login, TOTP, confirmaciones con contraseña).

Sin esto un atacante podía probar contraseñas o códigos TOTP (solo un millón de
combinaciones) sin límite. Contadores de ventana fija en Redis, con TTL: se consultan
ANTES de comprobar la contraseña (un bloqueado ni siquiera cuesta un hash) y solo los
FALLOS incrementan. Pensado para no dejar fuera a la persona legítima si otro le
falla su cuenta desde otra IP: el bloqueo por par (email, IP) es el más estricto, y
el de cuenta entera (cualquier IP) exige muchos más fallos.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

import redis.asyncio as redis
from fastapi import Request

from myfood.config import get_settings
from myfood.errors import AppError

_redis = redis.from_url(get_settings().redis_url, decode_responses=True)

_WINDOW_15_MIN = 15 * 60
_WINDOW_1_HOUR = 60 * 60


@dataclass(frozen=True)
class Rule:
    key: str
    limit: int
    window_seconds: int


def client_ip(request: Request) -> str:
    """IP real del cliente. La API solo es accesible a través del contenedor `web`, y
    el tráfico de fuera llega por Cloudflare, que fija `CF-Connecting-IP` (un cliente
    no puede falsearla: Cloudflare la sobrescribe); si no está, el primer salto de
    `X-Forwarded-For`, y por último la IP del socket."""
    forwarded = request.headers.get("cf-connecting-ip")
    if not forwarded:
        chain = request.headers.get("x-forwarded-for", "")
        forwarded = chain.split(",")[0].strip() if chain else ""
    return forwarded or (request.client.host if request.client else "unknown")


def _digest(value: str) -> str:
    # El email no se guarda en claro en las claves de Redis.
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()[:24]


def login_rules(email: str, ip: str) -> tuple[Rule, Rule, Rule]:
    email_hash = _digest(email)
    return (
        Rule(f"rl:login:pair:{email_hash}:{ip}", 5, _WINDOW_15_MIN),
        Rule(f"rl:login:email:{email_hash}", 20, _WINDOW_1_HOUR),
        Rule(f"rl:login:ip:{ip}", 30, _WINDOW_15_MIN),
    )


def totp_rules(mfa_token: str, user_id: UUID) -> tuple[Rule, Rule]:
    return (
        Rule(f"rl:totp:challenge:{_digest(mfa_token)}", 5, 5 * 60),
        Rule(f"rl:totp:user:{user_id}", 10, _WINDOW_15_MIN),
    )


def password_confirm_rules(action: str, user_id: UUID) -> tuple[Rule]:
    return (Rule(f"rl:pwd:{action}:{user_id}", 5, _WINDOW_15_MIN),)


async def guard(*rules: Rule) -> None:
    """429 si alguna regla ya llegó a su límite (no incrementa nada)."""
    for rule in rules:
        raw = await _redis.get(rule.key)
        if raw is not None and int(raw) >= rule.limit:
            retry_after = max(await _redis.ttl(rule.key), 1)
            minutes = max(1, -(-retry_after // 60))
            raise AppError(
                "AUTH_RATE_LIMITED",
                f"Demasiados intentos fallidos. Inténtalo de nuevo en {minutes} min.",
                status_code=429,
                details={"retry_after_seconds": retry_after},
            )


async def record_failure(*rules: Rule) -> None:
    for rule in rules:
        count = await _redis.incr(rule.key)
        if count == 1:
            await _redis.expire(rule.key, rule.window_seconds)


async def reset(*rules: Rule) -> None:
    if rules:
        await _redis.delete(*[rule.key for rule in rules])
