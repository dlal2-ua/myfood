"""Tests HTTP de `POST /log/smart` (sección 10.8). `request_smart_log` en
sí ya está probado en `test_smart_log_flow.py` — aquí solo se ejercita el
cableado del endpoint (consentimiento, cuotas, credencial) igual que
`test_ai_router.py` hace para `/ai/diet-plan`, y el ciclo completo de un
plato guardado: estimar, aprobar guardándolo, y que la siguiente vez no
haga falta ni el modelo ni la cuota."""

from datetime import date

import pytest_asyncio
from sqlalchemy import text

from myfood.ai import client as ai_client
from myfood.ai.queue import DIET_PLAN_QUEUE_KEY, SMART_LOG_QUEUE_KEY
from myfood.ai.queue import _redis as queue_redis
from myfood.config import get_settings
from myfood.db.models import AiProposal, Profile
from myfood.db.session import AdminSessionLocal
from myfood.domain import diary_proposal


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


async def test_a_saved_dish_is_logged_again_without_model_or_quota(
    ready_user, superuser_conn, monkeypatch
):
    """El ciclo que se pidió, por HTTP: se aprueba una estimación marcando «guardar en el
    catálogo» y, desde entonces, nombrar ese plato devuelve la propuesta al momento — sin
    encolar nada y sin gastar la cuota del día, que aquí está a cero."""
    from myfood.ai.limits import IafoodLimits
    from myfood.routers import ai as ai_router

    client, user_id = ready_user
    await client.post("/api/consents", json={"kind": "ai_processing", "version": "v1"})
    indexed = []

    async def _fake_index(food, nutrients):
        indexed.append(food.name_es)

    monkeypatch.setattr(ai_router, "index_food", _fake_index)

    # Una estimación pendiente, como la que deja el worker.
    async with AdminSessionLocal() as session:
        payload = await diary_proposal.build_payload(
            session,
            {
                "date": date.today().isoformat(),
                "meal_type": "morning_snack",
                "items": [
                    {
                        "nombre": "marinera",
                        "gramos": 130,
                        "kcal": 260,
                        "componentes": [
                            {"nombre": "rosquilla", "gramos": 60, "kcal": 160},
                            {"nombre": "ensaladilla rusa", "gramos": 70, "kcal": 100},
                        ],
                    }
                ],
            },
            alias_to_candidate={},
            today=date.today(),
        )
        first = await client.post("/api/log/smart", json={"text": "una marinera"})
        assert first.status_code == 202 and first.json()["status"] == "running"
        proposal = AiProposal(
            ai_session_id=first.json()["id"],
            user_id=user_id,
            scope="diary",
            payload=payload,
            status="pending",
        )
        session.add(proposal)
        await session.commit()
        proposal_id = proposal.id

    approved = await client.post(
        f"/api/ai/proposals/{proposal_id}/approve", json={"save_to_catalog": [0]}
    )
    assert approved.status_code == 200
    assert indexed == ["Marinera"]  # sale ya en el buscador

    try:
        monkeypatch.setattr(
            "myfood.ai.quota.load_limits",
            lambda: IafoodLimits(per_profile_daily=1, instance_daily=1, max_tokens_per_call=8000),
        )
        queue_before = await queue_redis.llen(SMART_LOG_QUEUE_KEY)
        again = await client.post(
            "/api/log/smart", json={"text": "Hoy a media mañana me he tomado dos marineras"}
        )
        assert again.status_code == 202
        body = again.json()
        assert body["status"] == "succeeded"
        assert body["response_payload"]["from_saved"] is True
        item = body["response_payload"]["proposal"]["payload"]["items"][0]
        assert (item["name"], item["quantity"], item["kcal"]) == ("Marinera", 2, 520)
        assert await queue_redis.llen(SMART_LOG_QUEUE_KEY) == queue_before

        # Y esa propuesta se aprueba como cualquier otra, sin cuerpo.
        second_id = body["response_payload"]["proposal"]["ai_proposal_id"]
        assert (await client.post(f"/api/ai/proposals/{second_id}/approve")).status_code == 200
        day = (await client.get(f"/api/log?date={date.today().isoformat()}")).json()
        assert sorted(e["kcal"] for e in day["food"]) == [260, 520]
        assert {e["food_name"] for e in day["food"]} == {"Marinera"}
    finally:
        await superuser_conn.execute(
            text(
                "DELETE FROM food_log WHERE food_id IN "
                "(SELECT id FROM foods WHERE source = 'ai_estimate')"
            )
        )
        await superuser_conn.execute(text("DELETE FROM foods WHERE source = 'ai_estimate'"))
        await superuser_conn.commit()
