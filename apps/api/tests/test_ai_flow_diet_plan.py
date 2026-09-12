"""Tests del flujo de generación de dietas con iafood (sección 10.6).
`process_diet_plan_job` (la mitad que corre en el `worker`) se prueba
construyendo el `ai_session.request_payload` a mano en vez de pasando por
`request_diet_plan` — así los candidatos y los objetivos del día son
totalmente deterministas (los mismos valores ya verificados a mano en
`test_diet_engine.py`), sin depender del catálogo real de 21k alimentos
para que la IA "elija" algo concreto y predecible."""

import uuid
from datetime import date

import pytest_asyncio
from sqlalchemy import select, text

from myfood.ai import client as ai_client
from myfood.ai.agent import AgentResult, AiAgentError
from myfood.ai.flows import diet_plan as flow
from myfood.db.models import AiProposal, AiSession, BodyMeasurement, DietPlan, Profile
from myfood.db.session import AdminSessionLocal

# Mismos 4 alimentos que BASIC_CANDIDATES en test_diet_engine.py. El
# objetivo es justo la combinación exacta (350/300/80/200 g) que produce
# `solve_day_with_fixed_items` para estos 4 alimentos — desviación cero
# garantizada, verificado a mano contra el solver real antes de fijar estos
# números — y por encima del suelo de seguridad (~1635 kcal) y del mínimo
# hormonal de grasa (35 g) del perfil de prueba de `profile_ready` (70 kg).
_DAY_TARGETS = {"kcal": 1742.7, "protein_g": 122.2, "fat_g": 94.3, "carbs_g": 98.0}
_FOOD_SPECS = [
    ("c1", "Pechuga de pollo (test)", 165, 31, 3.6, 0),
    ("c2", "Arroz blanco cocido (test)", 130, 2.7, 0.3, 28),
    ("c3", "Aceite de oliva (test)", 884, 0, 100, 0),
    ("c4", "Brócoli (test)", 34, 2.8, 0.4, 7),
]


@pytest_asyncio.fixture
async def four_real_foods(superuser_conn):
    ids = {alias: uuid.uuid4() for alias, *_ in _FOOD_SPECS}
    for alias, name, kcal, protein, fat, carbs in _FOOD_SPECS:
        food_id = ids[alias]
        await superuser_conn.execute(
            text(
                "INSERT INTO foods (id, kind, source, source_id, license, name_es, quality_rank) "
                "VALUES (:id, 'generic', 'test', :sid, 'CC0', :name, 1)"
            ),
            {"id": str(food_id), "sid": str(food_id), "name": name},
        )
        await superuser_conn.execute(
            text(
                "INSERT INTO food_nutrients "
                "(food_id, kcal_100g, protein_100g, fat_100g, carbs_100g, micros) "
                "VALUES (:id, :kcal, :protein, :fat, :carbs, '{}'::jsonb)"
            ),
            {"id": str(food_id), "kcal": kcal, "protein": protein, "fat": fat, "carbs": carbs},
        )
    await superuser_conn.commit()
    yield {alias: str(fid) for alias, fid in ids.items()}
    await superuser_conn.execute(
        text("DELETE FROM plan_items WHERE food_id = ANY(:ids)"),
        {"ids": list(ids.values())},
    )
    await superuser_conn.execute(
        text("DELETE FROM foods WHERE id = ANY(:ids)"), {"ids": list(ids.values())}
    )
    await superuser_conn.commit()


@pytest_asyncio.fixture
async def profile_ready(two_users):
    """Perfil completo + peso — lo que `process_diet_plan_job` necesita
    para recalcular el suelo de seguridad (R6) y el mínimo hormonal de
    grasa, siempre en fresco desde la BD (nunca desde `ai_sessions`)."""
    user_id, _ = two_users
    async with AdminSessionLocal() as session:
        profile = await session.get(Profile, user_id)
        profile.sex = "male"
        profile.birth_date = date(1994, 1, 1)
        profile.height_cm = 175
        profile.activity_level = "moderate"
        profile.goal = "maintain"
        profile.meals_per_day = 1
        session.add(BodyMeasurement(user_id=user_id, measured_on=date.today(), weight_kg=70))
        await session.commit()
    return user_id


@pytest_asyncio.fixture
async def configured_credential(two_users):
    admin_id, _ = two_users
    async with AdminSessionLocal() as session:
        await ai_client.set_credential(session, admin_user_id=admin_id, token="fake-test-token")
    yield
    async with AdminSessionLocal() as session:
        await session.execute(text("DELETE FROM ai_credentials"))
        await session.commit()


def _build_request_payload(food_ids: dict[str, str]) -> dict:
    return {
        "prompt_version": "diet_plan_v1",
        "num_days": 1,
        "meal_types": ["lunch"],
        "anonymized": {
            "targets": _DAY_TARGETS,
            "context": {
                "sex": "male",
                "age_band": "25-34",
                "activity_level": "moderate",
                "goal": "maintain",
                "meals_per_day": 1,
                "diet_style": None,
                "max_cook_minutes": None,
                "budget_band": None,
            },
            "restrictions": {"allergens": [], "disliked": []},
            "candidates": [
                {
                    "id": alias,
                    "name": name,
                    "category": None,
                    "kcal_100g": kcal,
                    "protein_100g": protein,
                    "fat_100g": fat,
                    "carbs_100g": carbs,
                }
                for alias, name, kcal, protein, fat, carbs in _FOOD_SPECS
            ],
        },
        "alias_to_food_id": food_ids,
    }


@pytest_asyncio.fixture
async def running_session(profile_ready, four_real_foods):
    async with AdminSessionLocal() as session:
        ai_session = AiSession(
            user_id=profile_ready,
            kind="diet_plan",
            status="running",
            request_payload=_build_request_payload(four_real_foods),
        )
        session.add(ai_session)
        await session.commit()
        await session.refresh(ai_session)
    return ai_session.id


def _fake_agent_call(plan_args: dict):
    async def _fake_run_agent(
        *, token, prompt, system_prompt, mcp_tools, max_turns, timeout_seconds
    ):
        await mcp_tools[0].handler(plan_args)
        return AgentResult(text="", input_tokens=10, output_tokens=5)

    return _fake_run_agent


async def _reload_session(session_id) -> AiSession:
    async with AdminSessionLocal() as session:
        return await session.get(AiSession, session_id)


async def test_success_path_creates_plan_and_pending_proposal(
    running_session, four_real_foods, configured_credential, monkeypatch
):
    plan_args = {
        "days": [
            {
                "day_index": 0,
                "meals": [
                    {
                        "meal_type": "lunch",
                        "items": [
                            {"alias": "c1", "approx_portion": "medium"},
                            {"alias": "c2", "approx_portion": "medium"},
                            {"alias": "c3", "approx_portion": "small"},
                            {"alias": "c4", "approx_portion": "medium"},
                        ],
                    }
                ],
            }
        ],
        "rationale": "Plan de prueba equilibrado.",
    }
    monkeypatch.setattr(flow, "run_agent", _fake_agent_call(plan_args))

    await flow.process_diet_plan_job(str(running_session))

    ai_session = await _reload_session(running_session)
    assert ai_session.status == "succeeded"
    assert ai_session.attempts == 1
    assert ai_session.response_payload["days_proposed"] == 1
    assert ai_session.input_tokens == 10
    assert ai_session.output_tokens == 5

    async with AdminSessionLocal() as session:
        proposals = (
            await session.scalars(
                select(AiProposal).where(AiProposal.ai_session_id == running_session)
            )
        ).all()
        assert len(proposals) == 1
        proposal = proposals[0]
        assert proposal.status == "pending"
        assert proposal.scope == "meal"
        assert proposal.rationale == "Plan de prueba equilibrado."
        assert proposal.payload["day_index"] == 0
        meal = proposal.payload["meals"][0]
        assert meal["meal_type"] == "lunch"
        selected_food_ids = {item["food_id"] for item in meal["items"]}
        assert selected_food_ids == set(four_real_foods.values())
        for item in meal["items"]:
            assert 20.0 <= item["grams"] <= 400.0

        plan = await session.get(DietPlan, uuid.UUID(ai_session.response_payload["diet_plan_id"]))
        assert plan.generated_by == "iafood"
        assert plan.status == "draft"


async def test_no_tool_call_is_rejected_after_retry(
    running_session, configured_credential, monkeypatch
):
    async def _fake_run_agent(
        *, token, prompt, system_prompt, mcp_tools, max_turns, timeout_seconds
    ):
        return AgentResult(text="no puedo ayudar con eso", input_tokens=1, output_tokens=1)

    monkeypatch.setattr(flow, "run_agent", _fake_run_agent)

    await flow.process_diet_plan_job(str(running_session))

    ai_session = await _reload_session(running_session)
    assert ai_session.status == "rejected_validation"
    assert ai_session.attempts == 2
    codes = {e["code"] for e in ai_session.validation_errors}
    assert "NO_TOOL_CALL" in codes


async def test_unknown_alias_is_rejected_after_retry(
    running_session, configured_credential, monkeypatch
):
    plan_args = {
        "days": [
            {
                "day_index": 0,
                "meals": [
                    {
                        "meal_type": "lunch",
                        "items": [{"alias": "ghost", "approx_portion": "medium"}],
                    }
                ],
            }
        ]
    }
    monkeypatch.setattr(flow, "run_agent", _fake_agent_call(plan_args))

    await flow.process_diet_plan_job(str(running_session))

    ai_session = await _reload_session(running_session)
    assert ai_session.status == "rejected_validation"
    assert ai_session.attempts == 2
    codes = {e["code"] for e in ai_session.validation_errors}
    assert "UNKNOWN_ALIAS" in codes


async def test_agent_error_marks_session_failed(
    running_session, configured_credential, monkeypatch
):
    async def _fake_run_agent(
        *, token, prompt, system_prompt, mcp_tools, max_turns, timeout_seconds
    ):
        raise AiAgentError("boom", code="AI_TIMEOUT")

    monkeypatch.setattr(flow, "run_agent", _fake_run_agent)

    await flow.process_diet_plan_job(str(running_session))

    ai_session = await _reload_session(running_session)
    assert ai_session.status == "failed"
    assert ai_session.validation_errors[0]["code"] == "AI_TIMEOUT"
    assert ai_session.validation_errors[0]["message"] == "boom"


async def test_agent_error_default_code_is_provider_error(
    running_session, configured_credential, monkeypatch
):
    """`AiAgentError` sin `code` explícito (p. ej. un fallo del SDK que no
    encaja en ninguna categoría concreta) usa un código genérico, nunca
    "AI_TIMEOUT" a secas — ese código es específico de un timeout real."""

    async def _fake_run_agent(
        *, token, prompt, system_prompt, mcp_tools, max_turns, timeout_seconds
    ):
        raise AiAgentError("algo salió mal")

    monkeypatch.setattr(flow, "run_agent", _fake_run_agent)

    await flow.process_diet_plan_job(str(running_session))

    ai_session = await _reload_session(running_session)
    assert ai_session.status == "failed"
    assert ai_session.validation_errors[0]["code"] == "AI_PROVIDER_ERROR"


async def test_missing_credential_marks_session_failed(running_session):
    await flow.process_diet_plan_job(str(running_session))

    ai_session = await _reload_session(running_session)
    assert ai_session.status == "failed"
    assert ai_session.validation_errors[0]["code"] == "AI_NOT_CONFIGURED"


async def test_already_processed_session_is_left_untouched(running_session, configured_credential):
    async with AdminSessionLocal() as session:
        ai_session = await session.get(AiSession, running_session)
        ai_session.status = "succeeded"
        await session.commit()

    await flow.process_diet_plan_job(str(running_session))

    ai_session = await _reload_session(running_session)
    assert ai_session.status == "succeeded"
