"""Tests HTTP de `routers/ai.py` (sección 7.7). El pipeline completo
(worker real llamando al Agent SDK) no corre en estos tests — para
`/proposals/*` se construyen `AiSession`/`AiProposal`/`DietPlan` a mano
directamente en BD, exactamente como dejaría el worker tras un éxito real,
y se ejercitan solo los endpoints HTTP de aprobar/rechazar/listar."""

import uuid
from contextlib import asynccontextmanager
from datetime import date

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from myfood.ai import client as ai_client
from myfood.ai.queue import DIET_PLAN_QUEUE_KEY
from myfood.ai.queue import _redis as queue_redis
from myfood.config import get_settings
from myfood.db.models import AiProposal, AiSession, BodyMeasurement, DietPlan, Profile
from myfood.db.session import AdminSessionLocal
from myfood.main import app


@asynccontextmanager
async def _second_registered_client(superuser_conn):
    """Un segundo usuario real vía HTTP, independiente de `registered_client`
    — para probar que uno no ve los datos del otro (R3)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        email = f"other-{uuid.uuid4()}@test.myfood"
        resp = await client.post(
            "/api/auth/register",
            json={"email": email, "password": "correcthorse123", "display_name": "Other"},
        )
        user_id = resp.json()["id"]
        try:
            yield client, uuid.UUID(user_id)
        finally:
            await superuser_conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
            await superuser_conn.commit()


@pytest_asyncio.fixture(autouse=True)
async def _iafood_config_tmp_path(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "iafood_config_path", str(tmp_path / "iafood.json"))


@pytest_asyncio.fixture(autouse=True)
async def _clean_ai_credential_and_queue(registered_client):
    # Depende explícitamente de `registered_client` para que pytest lo
    # desmonte ANTES (LIFO) de que ese fixture borre su usuario de prueba
    # — `ready_user` guarda `updated_by=user_id` en `ai_credentials`, y esa
    # FK bloquearía el DELETE de `users` si el orden fuera al revés (mismo
    # problema ya resuelto en test_admin.py).
    yield
    async with AdminSessionLocal() as session:
        await session.execute(text("DELETE FROM ai_credentials"))
        await session.commit()
    await queue_redis.delete(DIET_PLAN_QUEUE_KEY)


@pytest_asyncio.fixture
async def ready_user(registered_client, diet_candidates):
    """Perfil completo + peso + credencial configurada + candidatos
    garantizados (`diet_candidates`, ver conftest.py — sin ellos
    `select_candidates` devuelve vacío en un entorno sin el catálogo real,
    como CI) — todo lo que hace falta para que `POST /ai/diet-plan` llegue
    a encolar un trabajo (sin consentimiento todavía, cada test lo concede
    si lo necesita)."""
    client, user_id = registered_client
    async with AdminSessionLocal() as session:
        profile = await session.get(Profile, user_id)
        if profile is None:
            profile = Profile(user_id=user_id)
            session.add(profile)
        profile.sex = "male"
        profile.birth_date = date(1994, 1, 1)
        profile.height_cm = 175
        profile.activity_level = "moderate"
        profile.goal = "maintain"
        profile.meals_per_day = 3
        session.add(BodyMeasurement(user_id=user_id, measured_on=date.today(), weight_kg=70))
        await ai_client.set_credential(session, admin_user_id=user_id, token="fake-token")
        await session.commit()
    return client, user_id


async def test_diet_plan_request_requires_consent(ready_user):
    client, _ = ready_user
    resp = await client.post("/api/ai/diet-plan", json={"num_days": 3})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "AI_CONSENT_REQUIRED"


async def test_diet_plan_request_succeeds_with_consent(ready_user):
    client, _ = ready_user
    await client.post("/api/consents", json={"kind": "ai_processing", "version": "v1"})

    resp = await client.post("/api/ai/diet-plan", json={"num_days": 3})

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "running"
    assert body["kind"] == "diet_plan"

    status_resp = await client.get(f"/api/ai/sessions/{body['id']}")
    assert status_resp.status_code == 200
    assert status_resp.json()["id"] == body["id"]


async def test_diet_plan_request_hits_profile_quota(ready_user, monkeypatch):
    from myfood.ai.limits import IafoodLimits

    client, _ = ready_user
    await client.post("/api/consents", json={"kind": "ai_processing", "version": "v1"})
    monkeypatch.setattr(
        "myfood.ai.quota.load_limits",
        lambda: IafoodLimits(per_profile_daily=1, instance_daily=1000, max_tokens_per_call=8000),
    )

    first = await client.post("/api/ai/diet-plan", json={"num_days": 1})
    assert first.status_code == 202

    second = await client.post("/api/ai/diet-plan", json={"num_days": 1})
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "AI_QUOTA_PROFILE"
    assert "reset_at" in second.json()["error"]["details"]


async def test_session_status_is_not_visible_to_another_user(ready_user, superuser_conn):
    client, _ = ready_user
    await client.post("/api/consents", json={"kind": "ai_processing", "version": "v1"})
    resp = await client.post("/api/ai/diet-plan", json={"num_days": 1})
    session_id = resp.json()["id"]

    async with _second_registered_client(superuser_conn) as (other_client, _other_user_id):
        other_resp = await other_client.get(f"/api/ai/sessions/{session_id}")
        assert other_resp.status_code == 404


async def test_get_unknown_session_is_404(ready_user):
    client, _ = ready_user
    resp = await client.get("/api/ai/sessions/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest_asyncio.fixture
async def pending_proposal(registered_client):
    """Estado tal y como lo dejaría el worker tras un éxito real: un
    `DietPlan` (generated_by='iafood') + un `ai_proposal` pendiente para su
    único día."""
    _client, user_id = registered_client
    async with AdminSessionLocal() as session:
        plan = DietPlan(
            user_id=user_id,
            name="Plan iafood",
            start_date=date.today(),
            end_date=date.today(),
            status="draft",
            target_kcal=2000,
            target_protein_g=140,
            target_fat_g=60,
            target_carbs_g=200,
            generated_by="iafood",
        )
        session.add(plan)
        await session.flush()

        ai_session = AiSession(
            user_id=user_id,
            kind="diet_plan",
            status="succeeded",
            request_payload={"prompt_version": "diet_plan_v1"},
        )
        session.add(ai_session)
        await session.flush()

        # alimento real para que plan_items.food_id tenga una fila válida
        food_id = "11111111-1111-1111-1111-111111111111"
        await session.execute(
            text(
                "INSERT INTO foods (id, kind, source, source_id, license, name_es, quality_rank) "
                "VALUES (:id, 'generic', 'test', :sid, 'CC0', 'Alimento de prueba', 1) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": food_id, "sid": food_id},
        )
        await session.execute(
            text(
                "INSERT INTO food_nutrients "
                "(food_id, kcal_100g, protein_100g, fat_100g, carbs_100g, micros) "
                "VALUES (:id, 165, 31, 3.6, 0, '{}'::jsonb) ON CONFLICT (food_id) DO NOTHING"
            ),
            {"id": food_id},
        )

        proposal = AiProposal(
            ai_session_id=ai_session.id,
            user_id=user_id,
            scope="meal",
            payload={
                "diet_plan_id": str(plan.id),
                "day_index": 0,
                "meals": [{"meal_type": "lunch", "items": [{"food_id": food_id, "grams": 200.0}]}],
            },
            rationale="Rationale de prueba.",
            status="pending",
        )
        session.add(proposal)
        await session.commit()
        await session.refresh(proposal)

    yield proposal.id, plan.id, user_id

    async with AdminSessionLocal() as session:
        await session.execute(text("DELETE FROM plan_items WHERE food_id = :id"), {"id": food_id})
        await session.execute(text("DELETE FROM foods WHERE id = :id"), {"id": food_id})
        await session.commit()


async def test_list_pending_proposals(registered_client, pending_proposal):
    client, _ = registered_client
    proposal_id, _plan_id, _user_id = pending_proposal

    resp = await client.get("/api/ai/proposals?status=pending")

    assert resp.status_code == 200
    ids = {p["id"] for p in resp.json()}
    assert str(proposal_id) in ids


async def test_approve_proposal_materializes_plan_day(registered_client, pending_proposal):
    client, _ = registered_client
    proposal_id, plan_id, _user_id = pending_proposal

    resp = await client.post(f"/api/ai/proposals/{proposal_id}/approve")

    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"

    async with AdminSessionLocal() as session:
        days = (
            await session.execute(
                text("SELECT day_index FROM plan_days WHERE plan_id = :plan_id"),
                {"plan_id": str(plan_id)},
            )
        ).all()
        assert [d.day_index for d in days] == [0]


async def test_reject_proposal_does_not_touch_plan(registered_client, pending_proposal):
    client, _ = registered_client
    proposal_id, plan_id, _user_id = pending_proposal

    resp = await client.post(f"/api/ai/proposals/{proposal_id}/reject")

    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"

    async with AdminSessionLocal() as session:
        days = (
            await session.execute(
                text("SELECT day_index FROM plan_days WHERE plan_id = :plan_id"),
                {"plan_id": str(plan_id)},
            )
        ).all()
        assert days == []


async def test_cannot_decide_a_proposal_twice(registered_client, pending_proposal):
    client, _ = registered_client
    proposal_id, _plan_id, _user_id = pending_proposal

    first = await client.post(f"/api/ai/proposals/{proposal_id}/reject")
    assert first.status_code == 200

    second = await client.post(f"/api/ai/proposals/{proposal_id}/approve")
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "PROPOSAL_NOT_PENDING"


async def test_proposal_not_visible_to_another_user(pending_proposal, superuser_conn):
    proposal_id, _plan_id, _user_id = pending_proposal

    async with _second_registered_client(superuser_conn) as (other_client, _other_user_id):
        resp = await other_client.get("/api/ai/proposals")
        assert resp.status_code == 200
        assert resp.json() == []

        approve_resp = await other_client.post(f"/api/ai/proposals/{proposal_id}/approve")
        assert approve_resp.status_code == 404
