"""Cuotas de iafood (`ai/quota.py`). Cada test usa un `scope` propio y único
para no tocar los contadores reales del Redis compartido (los de
`diet_plan`/`chat`/`smart_log` de usuarios reales) y borra sus claves al
terminar."""

import uuid

import pytest
import redis.asyncio as redis

from myfood.ai.quota import QuotaExceeded, check_and_consume_quota
from myfood.config import get_settings

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def scope():
    name = f"test-{uuid.uuid4()}"
    yield name
    client = redis.from_url(get_settings().redis_url, decode_responses=True)
    keys = [key async for key in client.scan_iter(match=f"iafood:quota:{name}:*")]
    if keys:
        await client.delete(*keys)
    await client.aclose()


async def test_per_profile_limit_is_enforced(scope):
    user_id = uuid.uuid4()
    await check_and_consume_quota(user_id, scope=scope, per_profile_limit=2)
    await check_and_consume_quota(user_id, scope=scope, per_profile_limit=2)
    with pytest.raises(QuotaExceeded) as exc_info:
        await check_and_consume_quota(user_id, scope=scope, per_profile_limit=2)
    assert exc_info.value.code == "AI_QUOTA_PROFILE"


async def test_instance_limit_is_enforced_by_default(scope, monkeypatch):
    from myfood.ai import quota
    from myfood.ai.limits import IafoodLimits

    monkeypatch.setattr(quota, "load_limits", lambda: IafoodLimits(instance_daily=2))
    # Tres usuarios distintos: ninguno agota su cuota de perfil, pero entre los
    # tres se agota la de la instancia.
    await check_and_consume_quota(uuid.uuid4(), scope=scope)
    await check_and_consume_quota(uuid.uuid4(), scope=scope)
    with pytest.raises(QuotaExceeded) as exc_info:
        await check_and_consume_quota(uuid.uuid4(), scope=scope)
    assert exc_info.value.code == "AI_QUOTA_INSTANCE"


async def test_chat_style_call_skips_instance_limit_but_keeps_profile_limit(scope, monkeypatch):
    """El chat solo tiene límite por perfil (sección 24.5): el `instance_daily`
    de la generación de dietas (30) no le aplica — antes dejaba el chat
    incoherente (50 por perfil, pero 30 en total para toda la casa)."""
    from myfood.ai import quota
    from myfood.ai.limits import IafoodLimits

    monkeypatch.setattr(quota, "load_limits", lambda: IafoodLimits(instance_daily=1))
    for _ in range(5):  # varios usuarios, muy por encima de instance_daily=1
        await check_and_consume_quota(
            uuid.uuid4(), scope=scope, per_profile_limit=50, enforce_instance=False
        )

    user_id = uuid.uuid4()
    await check_and_consume_quota(
        user_id, scope=scope, per_profile_limit=1, enforce_instance=False
    )
    with pytest.raises(QuotaExceeded) as exc_info:
        await check_and_consume_quota(
            user_id, scope=scope, per_profile_limit=1, enforce_instance=False
        )
    assert exc_info.value.code == "AI_QUOTA_PROFILE"


async def test_quota_status_does_not_consume(scope, monkeypatch):
    """Consultar cuánto queda no puede gastar cuota: si lo hiciera, la propia pantalla
    que avisa de que quedan pocas se las comería al abrirse."""
    from myfood.ai import quota
    from myfood.ai.limits import IafoodLimits

    monkeypatch.setattr(quota, "load_limits", lambda: IafoodLimits(per_profile_daily=5))
    user_id = uuid.uuid4()

    before = await quota.quota_status(user_id, scope=scope, enforce_instance=False)
    assert before == {
        "scope": scope,
        "used": 0,
        "limit": 5,
        "remaining": 5,
        "reset_at": before["reset_at"],
        "instance_limit": None,
        "instance_remaining": None,
    }

    for _ in range(3):
        await quota.quota_status(user_id, scope=scope, enforce_instance=False)
    await check_and_consume_quota(user_id, scope=scope, per_profile_limit=5)

    after = await quota.quota_status(user_id, scope=scope, enforce_instance=False)
    assert after["used"] == 1
    assert after["remaining"] == 4


async def test_quota_status_takes_the_tighter_of_the_two_limits(scope, monkeypatch):
    """Lo que puede hacer el usuario es el mínimo entre su cuota y la de la casa — si la
    compartida está agotada, no le quedan peticiones por mucho que le sobren las suyas."""
    from myfood.ai import quota
    from myfood.ai.limits import IafoodLimits

    monkeypatch.setattr(
        quota, "load_limits", lambda: IafoodLimits(per_profile_daily=10, instance_daily=2)
    )
    await check_and_consume_quota(uuid.uuid4(), scope=scope)
    await check_and_consume_quota(uuid.uuid4(), scope=scope)

    status = await quota.quota_status(uuid.uuid4(), scope=scope)
    assert status["limit"] == 10
    assert status["instance_remaining"] == 0
    assert status["remaining"] == 0
