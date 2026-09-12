"""Tests HTTP de `POST /log/smart` (sección 10.8). `request_smart_log` en
sí ya está probado en `test_smart_log_flow.py` — aquí solo se ejercita el
cableado del endpoint (consentimiento, cuotas, credencial) igual que
`test_ai_router.py` hace para `/ai/diet-plan`.

`search_foods` se simula en los tests que necesitan que la petición llegue
a 202: Meilisearch puede estar vacío en este entorno (CI no ejecuta el
ETL, igual que el problema ya resuelto para `diet_candidates` en
conftest.py) y ningún test HTTP debería depender de qué haya indexado."""

from datetime import date

import pytest_asyncio
from sqlalchemy import text

from myfood.ai import client as ai_client
from myfood.ai.flows import food_resolution
from myfood.ai.queue import DIET_PLAN_QUEUE_KEY, SMART_LOG_QUEUE_KEY
from myfood.ai.queue import _redis as queue_redis
from myfood.config import get_settings
from myfood.db.models import Profile
from myfood.db.session import AdminSessionLocal


async def _fake_search_foods(query, kind, limit, offset):
    return [
        {"id": "11111111-1111-1111-1111-111111111111", "name_es": "Huevo", "category": None}
    ], 1


@pytest_asyncio.fixture(autouse=True)
async def _iafood_config_tmp_path(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "iafood_config_path", str(tmp_path / "iafood.json"))


@pytest_asyncio.fixture(autouse=True)
async def _clean_ai_credential_and_queue(registered_client):
    # Depende de `registered_client` para desmontarse antes (LIFO) de que
    # borre su usuario — `ai_credentials.updated_by` es una FK a `users.id`
    # (mismo problema ya resuelto en test_admin.py/test_ai_router.py).
    yield
    async with AdminSessionLocal() as session:
        await session.execute(text("DELETE FROM ai_credentials"))
        await session.commit()
    await queue_redis.delete(SMART_LOG_QUEUE_KEY)
    await queue_redis.delete(DIET_PLAN_QUEUE_KEY)


@pytest_asyncio.fixture
async def ready_user(registered_client):
    client, user_id = registered_client
    async with AdminSessionLocal() as session:
        profile = await session.get(Profile, user_id)
        if profile is None:
            profile = Profile(user_id=user_id)
            session.add(profile)
        await ai_client.set_credential(session, admin_user_id=user_id, token="fake-token")
        await session.commit()
    return client, user_id


async def test_smart_log_requires_consent(ready_user):
    client, _ = ready_user
    resp = await client.post("/api/log/smart", json={"text": "dos huevos fritos"})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "AI_CONSENT_REQUIRED"


async def test_smart_log_requires_credential(registered_client):
    client, _ = registered_client
    await client.post("/api/consents", json={"kind": "ai_processing", "version": "v1"})

    resp = await client.post("/api/log/smart", json={"text": "dos huevos fritos"})

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "AI_NOT_CONFIGURED"


async def test_smart_log_succeeds_with_consent_and_credential_and_can_be_polled(
    ready_user, monkeypatch
):
    client, _ = ready_user
    monkeypatch.setattr(food_resolution, "search_foods", _fake_search_foods)
    await client.post("/api/consents", json={"kind": "ai_processing", "version": "v1"})

    resp = await client.post("/api/log/smart", json={"text": "dos huevos fritos"})

    assert resp.status_code == 202
    body = resp.json()
    assert body["kind"] == "smart_log"
    assert body["status"] == "running"

    status_resp = await client.get(f"/api/ai/sessions/{body['id']}")
    assert status_resp.status_code == 200
    assert status_resp.json()["id"] == body["id"]


async def test_smart_log_uses_its_own_quota_scope_separate_from_diet_plan(
    ready_user, monkeypatch
):
    """Agotar la cuota de Smart Log no debe bloquear la generación de
    planes de dieta (cuotas separadas, sección 24.5)."""
    from myfood.ai.limits import IafoodLimits

    client, user_id = ready_user
    monkeypatch.setattr(food_resolution, "search_foods", _fake_search_foods)
    await client.post("/api/consents", json={"kind": "ai_processing", "version": "v1"})
    monkeypatch.setattr(
        "myfood.ai.quota.load_limits",
        lambda: IafoodLimits(per_profile_daily=1, instance_daily=1000, max_tokens_per_call=8000),
    )

    first = await client.post("/api/log/smart", json={"text": "una manzana"})
    assert first.status_code == 202
    second = await client.post("/api/log/smart", json={"text": "otra manzana"})
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "AI_QUOTA_PROFILE"

    async with AdminSessionLocal() as session:
        profile = await session.get(Profile, user_id)
        profile.sex = "male"
        profile.birth_date = date(1994, 1, 1)
        profile.height_cm = 175
        profile.activity_level = "moderate"
        profile.goal = "maintain"
        profile.meals_per_day = 3
        await session.commit()

    diet_plan_resp = await client.post("/api/ai/diet-plan", json={"num_days": 1})
    # 422 (sin peso registrado) es una señal de que sí llegó a intentar
    # generar el plan — lo único que este test comprueba es que NO le
    # bloqueó la cuota ya agotada de Smart Log (eso sería un 429).
    assert diet_plan_resp.status_code != 429
