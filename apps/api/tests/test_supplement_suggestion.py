"""Sugerencia de suplementos con iafood (sección 10.7): lista blanca, bloqueos y propuestas."""

import json
import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text

from myfood.ai import client as ai_client
from myfood.ai.agent import AgentResult
from myfood.ai.flows import supplement_suggestion as flow
from myfood.db.models import AiProposal, AiSession, BodyMeasurement, Profile
from myfood.db.session import AdminSessionLocal
from myfood.domain import supplements_whitelist as wl

pytestmark = pytest.mark.asyncio

LOW_MICROS = {
    "magnesium_mg": 20,
    "vitamin_d_ug": 0.2,
    "calcium_mg": 40,
    "iron_mg": 1,
    "zinc_mg": 0.5,
    "vitamin_b12_ug": 0.1,
}


@pytest_asyncio.fixture
async def micro_food(superuser_conn):
    food_id = uuid.uuid4()
    await superuser_conn.execute(
        text(
            "INSERT INTO foods (id, kind, source, source_id, license, name_es, quality_rank) "
            "VALUES (:id, 'generic', 'test', :sid, 'CC0', 'Alimento con micros (test)', 1)"
        ),
        {"id": str(food_id), "sid": str(food_id)},
    )
    await superuser_conn.execute(
        text(
            "INSERT INTO food_nutrients (food_id, kcal_100g, protein_100g, fat_100g, carbs_100g, "
            "micros) VALUES (:id, 100, 5, 2, 15, CAST(:micros AS jsonb))"
        ),
        {"id": str(food_id), "micros": json.dumps(LOW_MICROS)},
    )
    await superuser_conn.commit()
    yield food_id
    await superuser_conn.execute(
        text("DELETE FROM food_log WHERE food_id = :id"), {"id": str(food_id)}
    )
    await superuser_conn.execute(text("DELETE FROM foods WHERE id = :id"), {"id": str(food_id)})
    await superuser_conn.commit()


async def _setup_user(client, user_id, *, birth_date=date(1990, 1, 1)):
    async with AdminSessionLocal() as session:
        profile = await session.get(Profile, user_id) or Profile(user_id=user_id)
        session.add(profile)
        profile.sex = "male"
        profile.birth_date = birth_date
        profile.height_cm = 178
        profile.activity_level = "moderate"
        profile.goal = "maintain"
        session.add(BodyMeasurement(user_id=user_id, measured_on=date.today(), weight_kg=70))
        await ai_client.set_credential(session, admin_user_id=user_id, token="fake-token")
        await session.commit()
    await client.post("/api/consents", json={"kind": "ai_processing", "version": "v1"})


async def _log_days(client, food_id, days, grams=300):
    for i in range(days):
        day = (date.today() - timedelta(days=i)).isoformat()
        resp = await client.post(
            "/api/log/food",
            json={"log_date": day, "meal_type": "lunch", "food_id": str(food_id), "grams": grams},
        )
        assert resp.status_code == 201


@pytest_asyncio.fixture
async def ready(registered_client, micro_food):
    client, user_id = registered_client
    await _setup_user(client, user_id)
    await _log_days(client, micro_food, 10)
    return client, user_id


async def _request(client):
    return await client.post("/api/ai/supplement-suggestions")


# --- bloqueos y requisitos -----------------------------------------------------------------------


async def test_a_ready_user_gets_a_running_session_with_an_anonymized_payload(ready):
    client, user_id = ready

    resp = await _request(client)

    assert resp.status_code == 202
    assert resp.json()["kind"] == "supplement_suggestion"
    async with AdminSessionLocal() as session:
        ai_session = await session.get(AiSession, uuid.UUID(resp.json()["id"]))
    payload = ai_session.request_payload["anonymized"]
    serialized = json.dumps(payload)
    assert str(user_id) not in serialized
    assert "@" not in serialized
    assert {n["key"] for n in payload["nutrients"]} == {
        "magnesium",
        "vitamin_d",
        "vitamin_b12",
        "iron",
        "zinc",
        "calcium",
    }
    assert payload["logging_days"] == 10
    assert {w["key"] for w in payload["whitelist"]} == set(wl.KEYS)
    magnesium = next(n for n in payload["nutrients"] if n["key"] == "magnesium")
    assert magnesium["avg_per_day"] == 60.0  # 300 g x 20 mg / 100 g
    assert magnesium["pct_of_reference"] == pytest.approx(17.1, abs=0.1)


async def test_it_needs_the_ai_consent(registered_client, micro_food):
    client, user_id = registered_client
    await _setup_user(client, user_id)
    await client.delete("/api/consents/ai_processing")
    await _log_days(client, micro_food, 10)
    resp = await _request(client)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "AI_CONSENT_REQUIRED"


@pytest.mark.parametrize("flag", ["is_pregnant_or_nursing", "has_medical_condition"])
async def test_a_declared_pregnancy_or_condition_blocks_the_flow(ready, flag):
    client, _ = ready
    assert (await client.put("/api/profile", json={flag: True})).status_code == 200

    resp = await _request(client)

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "SUPPLEMENT_ADVICE_BLOCKED"


async def test_a_minor_is_blocked(registered_client, micro_food):
    client, user_id = registered_client
    await _setup_user(client, user_id, birth_date=date.today() - timedelta(days=365 * 16))
    await _log_days(client, micro_food, 10)
    resp = await _request(client)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "SUPPLEMENT_ADVICE_BLOCKED"


async def test_without_a_birth_date_it_asks_to_complete_the_profile(registered_client, micro_food):
    client, user_id = registered_client
    await _setup_user(client, user_id)
    async with AdminSessionLocal() as session:
        profile = await session.get(Profile, user_id)
        profile.birth_date = None
        await session.commit()
    await _log_days(client, micro_food, 10)
    resp = await _request(client)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "PROFILE_INCOMPLETE"


async def test_too_few_logged_days_is_not_enough_data(registered_client, micro_food):
    client, user_id = registered_client
    await _setup_user(client, user_id)
    await _log_days(client, micro_food, 3)
    resp = await _request(client)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "NOT_ENOUGH_DATA"


async def test_foods_without_micronutrient_data_cannot_support_a_suggestion(
    registered_client, test_food
):
    client, user_id = registered_client
    await _setup_user(client, user_id)
    await _log_days(client, test_food, 10)  # el alimento de prueba no trae micronutrientes
    resp = await _request(client)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INSUFFICIENT_MICRONUTRIENT_DATA"


async def test_it_needs_the_iafood_credential(registered_client, micro_food):
    client, user_id = registered_client
    await _setup_user(client, user_id)
    async with AdminSessionLocal() as session:
        await session.execute(text("DELETE FROM ai_credentials"))
        await session.commit()
    await _log_days(client, micro_food, 10)
    resp = await _request(client)
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "AI_NOT_CONFIGURED"


async def test_it_has_its_own_daily_quota(ready, monkeypatch):
    from myfood.ai.limits import IafoodLimits

    client, _ = ready
    monkeypatch.setattr(
        "myfood.ai.quota.load_limits",
        lambda: IafoodLimits(per_profile_daily=1, instance_daily=1000, max_tokens_per_call=8000),
    )
    assert (await _request(client)).status_code == 202
    second = await _request(client)
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "AI_QUOTA_PROFILE"


async def test_the_health_flags_are_stored_encrypted(ready, superuser_conn):
    client, user_id = ready
    await client.put("/api/profile", json={"is_pregnant_or_nursing": True})

    out = (await client.get("/api/profile")).json()
    raw = (
        await superuser_conn.execute(
            text("SELECT health_flags FROM profiles WHERE user_id = :id"), {"id": str(user_id)}
        )
    ).scalar_one()

    assert out["is_pregnant_or_nursing"] is True
    assert out["has_medical_condition"] is False
    assert "pregnant" not in raw, "la declaración de salud no puede estar en claro (R4)"

    await client.put("/api/profile", json={"is_pregnant_or_nursing": False})
    assert (await client.get("/api/profile")).json()["is_pregnant_or_nursing"] is False


# --- lista blanca y validación --------------------------------------------------------------------


def test_every_whitelisted_dose_is_within_its_range_and_its_upper_limit():
    assert set(wl.KEYS) == {
        "protein", "creatine", "magnesium", "omega3", "vitamin_d", "vitamin_b12", "iron",
        "zinc", "calcium", "multivitamin",
    }  # fmt: skip
    for entry in wl.WHITELIST:
        dose = wl.suggested_dose(entry)
        assert entry.dose_min <= dose <= entry.dose_max
        if entry.upper_limit is not None:
            assert dose <= entry.upper_limit


def test_the_suggested_dose_never_exceeds_the_upper_limit():
    risky = wl.WhitelistedSupplement("x", "X", "x", 500, "mg", 100, 900, 250)
    assert wl.suggested_dose(risky) == 250


def test_an_existing_supplement_is_recognised_by_type_or_name():
    magnesium = wl.BY_KEY["magnesium"]
    assert wl.already_taking(magnesium, [("Citrato de magnesio", "other")])
    assert wl.already_taking(magnesium, [("Lo que sea", "magnesium")])
    assert not wl.already_taking(magnesium, [("Creatina", "creatine")])


PAYLOAD = {
    "already_taking": ["creatine"],
    "nutrients": [
        {
            "key": "magnesium",
            "label": "Magnesio",
            "avg_per_day": 60,
            "reference": 350,
            "pct_of_reference": 17.1,
        },
        {
            "key": "zinc",
            "label": "Zinc",
            "avg_per_day": 9,
            "reference": 9.4,
            "pct_of_reference": 95.7,
        },
    ],
    "protein": {"key": "protein", "avg_per_day_g": 90, "target_g": 140, "pct_of_target": 64.3},
}


def test_only_supported_whitelisted_new_suggestions_survive():
    raw = [
        {"key": "magnesium", "reason": "x"},
        {"key": "magnesium", "reason": "repetida"},
        {"key": "zinc", "reason": "ya llega a la referencia"},  # no lo apoyan los datos
        {"key": "creatine", "reason": "ya la toma"},
        {"key": "unobtanium", "reason": "no existe"},
        {"key": "vitamin_d", "reason": "sin dato de ingesta"},
        {"key": "protein", "reason": "poca proteína"},
        {"key": "omega3", "reason": "ningún dato de ingesta lo puede apoyar"},
    ]
    accepted = flow.validate_suggestions(raw, PAYLOAD)
    assert [a["key"] for a in accepted] == ["magnesium", "protein"]


def test_at_most_three_suggestions_are_kept():
    payload = {**PAYLOAD, "already_taking": [], "protein": None}
    payload["nutrients"] = [
        {"key": k, "label": k, "avg_per_day": 1, "reference": 10, "pct_of_reference": 10.0}
        for k in ("magnesium", "iron", "zinc", "calcium", "vitamin_d")
    ]
    raw = [{"key": k, "reason": "r"} for k in ("magnesium", "iron", "zinc", "calcium", "vitamin_d")]
    assert len(flow.validate_suggestions(raw, payload)) == 3


def test_the_backend_writes_the_numbers_and_drops_model_text_with_digits():
    with_digits = flow._reason({"key": "magnesium", "reason": "Toma 400 mg al día"}, PAYLOAD)
    assert "400" not in with_digits
    assert with_digits == "Tu ingesta media de magnesio es el 17.1 % de la referencia."

    clean = flow._reason({"key": "magnesium", "reason": "Conviene revisarlo."}, PAYLOAD)
    assert (
        clean == "Tu ingesta media de magnesio es el 17.1 % de la referencia. Conviene revisarlo."
    )


# --- el trabajo del worker y la aprobación --------------------------------------------------------


def _fake_agent(suggestions):
    async def _run(*, token, prompt, system_prompt, mcp_tools, max_turns, timeout_seconds):
        await mcp_tools[0].handler({"suggestions": suggestions})
        return AgentResult(text="", input_tokens=5, output_tokens=4)

    return _run


async def _run_job(client, monkeypatch, suggestions):
    monkeypatch.setattr(flow, "run_agent", _fake_agent(suggestions))
    session_id = (await _request(client)).json()["id"]
    await flow.process_supplement_suggestion_job(session_id)
    async with AdminSessionLocal() as session:
        return await session.get(AiSession, uuid.UUID(session_id))


async def test_the_job_creates_pending_proposals_with_backend_doses(ready, monkeypatch):
    client, _ = ready
    ai_session = await _run_job(
        client, monkeypatch, [{"key": "magnesium", "reason": "Conviene revisarlo."}]
    )

    assert ai_session.status == "succeeded"
    body = ai_session.response_payload
    assert body["disclaimer"] == wl.DISCLAIMER
    assert body["warning"] is None
    [suggestion] = body["suggestions"]
    assert suggestion["key"] == "magnesium"
    assert suggestion["dose_amount"] == 200  # la dosis la pone el backend
    assert suggestion["dose_unit"] == "mg"
    assert "17.1 %" in suggestion["reason"]
    async with AdminSessionLocal() as session:
        proposal = await session.get(AiProposal, uuid.UUID(suggestion["proposal_id"]))
    assert proposal.status == "pending"
    assert proposal.scope == "supplement"
    assert proposal.payload["disclaimer"] == wl.DISCLAIMER


async def test_a_dose_proposed_by_the_model_is_ignored(ready, monkeypatch):
    client, _ = ready
    ai_session = await _run_job(
        client, monkeypatch, [{"key": "magnesium", "reason": "ok", "dose_amount": 5000}]
    )
    assert ai_session.response_payload["suggestions"][0]["dose_amount"] == 200


async def test_nothing_supported_is_a_valid_empty_result(ready, monkeypatch):
    client, _ = ready
    ai_session = await _run_job(client, monkeypatch, [{"key": "unobtanium", "reason": "x"}])
    assert ai_session.status == "succeeded"
    assert ai_session.response_payload["suggestions"] == []
    assert ai_session.response_payload["warning"] == "NO_SUPPORTED_SUGGESTION"


async def test_no_tool_call_is_also_an_empty_result(ready, monkeypatch):
    client, _ = ready

    async def _silent(*, token, prompt, system_prompt, mcp_tools, max_turns, timeout_seconds):
        return AgentResult(text="no sugiero nada", input_tokens=1, output_tokens=1)

    monkeypatch.setattr(flow, "run_agent", _silent)
    session_id = (await _request(client)).json()["id"]
    await flow.process_supplement_suggestion_job(session_id)
    async with AdminSessionLocal() as session:
        ai_session = await session.get(AiSession, uuid.UUID(session_id))
    assert ai_session.response_payload["suggestions"] == []


async def test_approving_a_suggestion_adds_the_supplement_and_rejecting_adds_nothing(
    ready, monkeypatch
):
    client, _ = ready
    ai_session = await _run_job(
        client,
        monkeypatch,
        [{"key": "magnesium", "reason": "a"}, {"key": "vitamin_d", "reason": "b"}],
    )
    first, second = ai_session.response_payload["suggestions"]

    assert (await client.get("/api/supplements")).json()["items"] == []
    approved = await client.post(f"/api/ai/proposals/{first['proposal_id']}/approve")
    rejected = await client.post(f"/api/ai/proposals/{second['proposal_id']}/reject")

    assert approved.status_code == 200
    assert rejected.status_code == 200
    items = (await client.get("/api/supplements")).json()["items"]
    assert [(i["name"], i["dose_amount"], i["dose_unit"]) for i in items] == [
        ("Magnesio", 200.0, "mg")
    ]
    assert "orientativo" in items[0]["notes"]


async def test_a_supplement_already_taken_is_not_suggested_again(ready, monkeypatch):
    client, _ = ready
    await client.post(
        "/api/supplements",
        json={"name": "Magnesio bisglicinato", "type": "other", "dose_amount": 1, "dose_unit": "u"},
    )
    ai_session = await _run_job(client, monkeypatch, [{"key": "magnesium", "reason": "x"}])
    assert ai_session.response_payload["suggestions"] == []


async def test_a_failing_agent_marks_the_session_failed(ready, monkeypatch):
    from myfood.ai.agent import AiAgentError

    client, _ = ready

    async def _boom(**kwargs):
        raise AiAgentError("tardó demasiado", code="AI_TIMEOUT")

    monkeypatch.setattr(flow, "run_agent", _boom)
    session_id = (await _request(client)).json()["id"]
    await flow.process_supplement_suggestion_job(session_id)
    async with AdminSessionLocal() as session:
        ai_session = await session.get(AiSession, uuid.UUID(session_id))
    assert ai_session.status == "failed"
    assert ai_session.validation_errors[0]["code"] == "AI_TIMEOUT"
