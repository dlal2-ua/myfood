import secrets
from uuid import UUID

import redis.asyncio as redis
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from myfood.config import get_settings

settings = get_settings()
_hasher = PasswordHasher()
_redis = redis.from_url(settings.redis_url, decode_responses=True)

SESSION_COOKIE_NAME = "myfood_session"
_SESSION_KEY_PREFIX = "session:"

# Reto de segundo factor (Fase 7): tras validar email+contraseña de una
# cuenta con TOTP activo, `login` no emite todavía la cookie de sesión real
# — emite este token de vida corta, que solo sirve para canjearlo por el
# código TOTP en `/auth/2fa/verify-login`. TTL corto a propósito: es una
# ventana para completar el segundo factor, no una sesión.
_MFA_CHALLENGE_KEY_PREFIX = "mfa_challenge:"
_MFA_CHALLENGE_TTL_SECONDS = 5 * 60


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


async def create_session(user_id: UUID) -> str:
    token = secrets.token_urlsafe(32)
    ttl_seconds = settings.session_ttl_days * 24 * 60 * 60
    await _redis.set(f"{_SESSION_KEY_PREFIX}{token}", str(user_id), ex=ttl_seconds)
    return token


async def get_session_user_id(token: str) -> UUID | None:
    raw = await _redis.get(f"{_SESSION_KEY_PREFIX}{token}")
    if raw is None:
        return None
    return UUID(raw)


async def destroy_session(token: str) -> None:
    await _redis.delete(f"{_SESSION_KEY_PREFIX}{token}")


async def create_mfa_challenge(user_id: UUID) -> str:
    token = secrets.token_urlsafe(32)
    await _redis.set(
        f"{_MFA_CHALLENGE_KEY_PREFIX}{token}", str(user_id), ex=_MFA_CHALLENGE_TTL_SECONDS
    )
    return token


async def get_mfa_challenge_user_id(token: str) -> UUID | None:
    raw = await _redis.get(f"{_MFA_CHALLENGE_KEY_PREFIX}{token}")
    if raw is None:
        return None
    return UUID(raw)


async def destroy_mfa_challenge(token: str) -> None:
    await _redis.delete(f"{_MFA_CHALLENGE_KEY_PREFIX}{token}")
