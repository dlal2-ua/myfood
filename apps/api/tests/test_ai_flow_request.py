"""Tests de `request_diet_plan` — la mitad del flujo de iafood que corre
en el proceso `api` (sección 10.6). A diferencia de
`test_ai_flow_diet_plan.py`, aquí sí se deja que `select_candidates`
consulte el catálogo real (21k+ alimentos) — solo hace falta confirmar que
prepara correctamente la sesión y encola el trabajo, no qué candidatos
concretos salen."""

from datetime import date

import pytest
from sqlalchemy import text

from myfood.ai import client as ai_client
from myfood.ai.flows import diet_plan as flow
from myfood.db.models import AiSession, BodyMeasurement, Profile
from myfood.db.session import AdminSessionLocal
from myfood.errors import AppError


async def _set_complete_profile(user_id) -> None:
    async with AdminSessionLocal() as session:
        profile = await session.get(Profile, user_id)
        profile.sex = "male"
        profile.birth_date = date(1994, 1, 1)
        profile.height_cm = 175
        profile.activity_level = "moderate"
        profile.goal = "maintain"
        profile.meals_per_day = 3
        session.add(BodyMeasurement(user_id=user_id, measured_on=date.today(), weight_kg=70))
        await session.commit()


async def _configure_credential(admin_id) -> None:
    async with AdminSessionLocal() as session:
        await ai_client.set_credential(session, admin_user_id=admin_id, token="fake-test-token")


async def _clear_credential() -> None:
    async with AdminSessionLocal() as session:
        await session.execute(text("DELETE FROM ai_credentials"))
        await session.commit()


async def test_raises_ai_not_configured_without_credential(two_users):
    user_id, _ = two_users
    await _set_complete_profile(user_id)
    try:
        async with AdminSessionLocal() as session:
            with pytest.raises(AppError) as exc_info:
                await flow.request_diet_plan(session, user_id, num_days=3)
        assert exc_info.value.code == "AI_NOT_CONFIGURED"
        assert exc_info.value.status_code == 503
    finally:
        await _clear_credential()


async def test_raises_profile_incomplete_even_with_credential(two_users):
    user_id, admin_id = two_users
    await _configure_credential(admin_id)
    try:
        async with AdminSessionLocal() as session:
            with pytest.raises(AppError) as exc_info:
                await flow.request_diet_plan(session, user_id, num_days=3)
        assert exc_info.value.code == "PROFILE_INCOMPLETE"
    finally:
        await _clear_credential()


async def test_creates_running_session_and_enqueues_job(two_users, diet_candidates, monkeypatch):
    user_id, admin_id = two_users
    await _set_complete_profile(user_id)
    await _configure_credential(admin_id)
    enqueued = []

    async def _fake_enqueue(ai_session_id: str) -> None:
        enqueued.append(ai_session_id)

    monkeypatch.setattr(flow, "enqueue_diet_plan_job", _fake_enqueue)

    try:
        async with AdminSessionLocal() as session:
            ai_session = await flow.request_diet_plan(session, user_id, num_days=3)

        assert ai_session.status == "running"
        assert ai_session.kind == "diet_plan"
        assert ai_session.user_id == user_id
        payload = ai_session.request_payload
        assert payload["num_days"] == 3
        assert payload["meal_types"] == ["breakfast", "lunch", "dinner"]
        assert payload["prompt_version"] == "diet_plan_v1"
        assert len(payload["anonymized"]["candidates"]) > 0
        assert len(payload["alias_to_food_id"]) == len(payload["anonymized"]["candidates"])
        # R5: ningún food_id real aparece en los propios candidatos anonimizados.
        for candidate in payload["anonymized"]["candidates"]:
            assert candidate["id"] not in payload["alias_to_food_id"].values()

        assert enqueued == [str(ai_session.id)]

        async with AdminSessionLocal() as session:
            reloaded = await session.get(AiSession, ai_session.id)
            assert reloaded is not None
            assert reloaded.status == "running"
    finally:
        await _clear_credential()
