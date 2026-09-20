"""Tests del chat conversacional (Fase 8, sección 24).

`process_chat_job` se prueba sin el Agent SDK real: se monkeypatchea
`chat.flow.run_chat_turn` (o, para los tests del bucle agente en sí,
`chat.agent_loop.run_agent`) con resultados fijos — mismo criterio que
`test_ai_flow_diet_plan.py`/`test_receipt_scan_flow.py`. Los candidatos y
objetivos de `test_day_change_*` son EXACTAMENTE los mismos 4 alimentos y
el mismo `_DAY_TARGETS` de `test_ai_flow_diet_plan.py` (desviación cero
verificada a mano contra el solver real) para no tener que re-derivar una
combinación numérica factible desde cero."""

import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from myfood.ai import client as ai_client
from myfood.ai.prompts import build_chat_user_prompt
from myfood.chat import flow
from myfood.chat.agent_loop import ChatTurnResult
from myfood.chat.tools import build_chat_tools
from myfood.chat.transcribe import TranscriptionUnavailable, transcribe
from myfood.db.models import AiProposal, AiSession, BodyMeasurement, ChatMessage, DietPlan, Profile
from myfood.db.session import AdminSessionLocal
from myfood.domain.diet_engine import CandidateFood
from myfood.errors import AppError

pytestmark = pytest.mark.asyncio

# Mismos 4 alimentos + objetivo que test_ai_flow_diet_plan.py — combinación
# ya verificada de desviación cero contra `solve_day_with_fixed_items`.
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
        text("DELETE FROM plan_items WHERE food_id = ANY(:ids)"), {"ids": list(ids.values())}
    )
    await superuser_conn.execute(
        text("DELETE FROM pantry_items WHERE food_id = ANY(:ids)"), {"ids": list(ids.values())}
    )
    await superuser_conn.execute(
        text("DELETE FROM foods WHERE id = ANY(:ids)"), {"ids": list(ids.values())}
    )
    await superuser_conn.commit()


@pytest_asyncio.fixture
async def low_kcal_food(superuser_conn):
    """Un único alimento de kcal muy baja — usado para forzar de forma
    determinista que el día resuelto quede por debajo del suelo de
    seguridad (R6, criterio de aceptación de la Fase 8), sin depender del
    catálogo real."""
    food_id = uuid.uuid4()
    await superuser_conn.execute(
        text(
            "INSERT INTO foods (id, kind, source, source_id, license, name_es, quality_rank) "
            "VALUES (:id, 'generic', 'test', :sid, 'CC0', 'Lechuga (test)', 1)"
        ),
        {"id": str(food_id), "sid": str(food_id)},
    )
    await superuser_conn.execute(
        text(
            "INSERT INTO food_nutrients "
            "(food_id, kcal_100g, protein_100g, fat_100g, carbs_100g, micros) "
            "VALUES (:id, 15, 1.2, 0.2, 2.9, '{}'::jsonb)"
        ),
        {"id": str(food_id)},
    )
    await superuser_conn.commit()
    yield str(food_id)
    await superuser_conn.execute(
        text("DELETE FROM plan_items WHERE food_id = :id"), {"id": str(food_id)}
    )
    await superuser_conn.execute(text("DELETE FROM foods WHERE id = :id"), {"id": str(food_id)})
    await superuser_conn.commit()


@pytest_asyncio.fixture
async def profile_ready(two_users):
    user_id, _ = two_users
    async with AdminSessionLocal() as session:
        profile = await session.get(Profile, user_id)
        profile.sex = "male"
        profile.birth_date = date(1994, 1, 1)
        profile.height_cm = 175
        profile.activity_level = "moderate"
        profile.goal = "maintain"
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


@pytest_asyncio.fixture
async def active_plan(profile_ready):
    """Plan activo de un solo día/una comida ('lunch') con un item cualquiera
    — lo único que le importa a `_build_day_change_proposal` es que exista
    un `PlanDay(day_index=0)` con fecha de hoy y los `target_*` conocidos."""
    async with AdminSessionLocal() as session:
        plan = DietPlan(
            user_id=profile_ready,
            name="Plan de prueba",
            start_date=date.today(),
            end_date=date.today(),
            status="active",
            target_kcal=_DAY_TARGETS["kcal"],
            target_protein_g=_DAY_TARGETS["protein_g"],
            target_fat_g=_DAY_TARGETS["fat_g"],
            target_carbs_g=_DAY_TARGETS["carbs_g"],
            generated_by="manual",
        )
        session.add(plan)
        await session.flush()
        await session.execute(
            text("INSERT INTO plan_days (id, plan_id, day_index) VALUES (:id, :plan_id, 0)"),
            {"id": str(uuid.uuid4()), "plan_id": str(plan.id)},
        )
        await session.commit()
        await session.refresh(plan)
    return plan.id, profile_ready


async def _noop_enqueue(session_id: str) -> None:
    pass


def _fake_push(store: dict):
    async def _fake(session_id: str, payload: dict) -> None:
        store.update(payload)

    return _fake


def _running_ai_session(user_id, payload) -> AiSession:
    return AiSession(user_id=user_id, kind="chat_edit", status="running", request_payload=payload)


async def _reload_session(session_id) -> AiSession:
    async with AdminSessionLocal() as session:
        return await session.get(AiSession, session_id)


# --- _build_day_change_proposal (acceptance criteria #1 and #5) -------------


async def test_day_change_proposal_success(active_plan, four_real_foods):
    plan_id, user_id = active_plan
    alias_to_candidate = {
        alias: CandidateFood(
            id=four_real_foods[alias], name_es=name, kcal_100g=kcal,
            protein_100g=protein, fat_100g=fat, carbs_100g=carbs,
        )
        for alias, name, kcal, protein, fat, carbs in _FOOD_SPECS
    }
    day_change_args = {
        "date": date.today().isoformat(),
        "meals": [
            {
                "meal_type": "lunch",
                "items": [{"alias": a, "approx_portion": "medium"} for a in alias_to_candidate],
            }
        ],
    }
    turn = ChatTurnResult(
        text="Vale, te cambio la comida.",
        day_change_args=day_change_args,
        pantry_args=None,
        alias_to_candidate=alias_to_candidate,
        input_tokens=5,
        output_tokens=3,
    )

    async with AdminSessionLocal() as session:
        ai_session = _running_ai_session(user_id, {"source": "text", "text": "cámbiame la comida"})
        session.add(ai_session)
        await session.commit()
        await session.refresh(ai_session)

        proposal_out, error = await flow._build_day_change_proposal(
            session, user_id, ai_session, turn
        )
        await session.commit()

    assert error is None
    assert proposal_out is not None
    assert proposal_out["scope"] == "day"
    payload = proposal_out["payload"]
    assert payload["diet_plan_id"] == str(plan_id)
    assert payload["day_index"] == 0
    meal = payload["meals"][0]
    assert meal["meal_type"] == "lunch"
    selected_food_ids = {item["food_id"] for item in meal["items"]}
    assert selected_food_ids == set(four_real_foods.values())
    for item in meal["items"]:
        assert 20.0 <= item["grams"] <= 400.0

    async with AdminSessionLocal() as session:
        proposal = await session.get(AiProposal, uuid.UUID(proposal_out["ai_proposal_id"]))
        assert proposal.status == "pending"
        assert proposal.scope == "day"


async def test_day_change_proposal_blocks_below_safety_floor(active_plan, low_kcal_food):
    """R6 — criterio de aceptación explícito de la Fase 8: un cambio que
    dejaría al usuario por debajo del suelo de seguridad calórico se
    rechaza, aunque el modelo lo haya propuesto tal cual."""
    plan_id, user_id = active_plan
    alias_to_candidate = {
        "c1": CandidateFood(
            id=low_kcal_food, name_es="Lechuga (test)", kcal_100g=15,
            protein_100g=1.2, fat_100g=0.2, carbs_100g=2.9,
        )
    }
    day_change_args = {
        "date": date.today().isoformat(),
        "meals": [
            {"meal_type": "lunch", "items": [{"alias": "c1", "approx_portion": "large"}]}
        ],
    }
    turn = ChatTurnResult(
        text="", day_change_args=day_change_args, pantry_args=None,
        alias_to_candidate=alias_to_candidate,
    )

    async with AdminSessionLocal() as session:
        ai_session = _running_ai_session(user_id, {"source": "text", "text": "solo lechuga hoy"})
        session.add(ai_session)
        await session.commit()
        await session.refresh(ai_session)

        proposal_out, error = await flow._build_day_change_proposal(
            session, user_id, ai_session, turn
        )
        await session.commit()

        assert proposal_out is None
        assert error is not None
        assert "suelo de seguridad" in error

        remaining = (
            await session.scalars(
                select(AiProposal).where(AiProposal.ai_session_id == ai_session.id)
            )
        ).all()
        assert remaining == []
    del plan_id


async def test_day_change_proposal_no_active_plan(profile_ready):
    user_id = profile_ready
    turn = ChatTurnResult(
        text="",
        day_change_args={"date": date.today().isoformat(), "meals": []},
        pantry_args=None,
        alias_to_candidate={},
    )
    async with AdminSessionLocal() as session:
        ai_session = _running_ai_session(user_id, {"source": "text", "text": "cámbiame la cena"})
        session.add(ai_session)
        await session.commit()
        await session.refresh(ai_session)

        proposal_out, error = await flow._build_day_change_proposal(
            session, user_id, ai_session, turn
        )
        assert proposal_out is None
        assert "ningún plan activo" in error


async def test_day_change_proposal_unknown_alias_is_rejected(active_plan):
    plan_id, user_id = active_plan
    turn = ChatTurnResult(
        text="",
        day_change_args={
            "date": date.today().isoformat(),
            "meals": [
                {"meal_type": "lunch", "items": [{"alias": "ghost", "approx_portion": "medium"}]}
            ],
        },
        pantry_args=None,
        alias_to_candidate={},
    )
    async with AdminSessionLocal() as session:
        ai_session = _running_ai_session(user_id, {"source": "text", "text": "algo raro"})
        session.add(ai_session)
        await session.commit()
        await session.refresh(ai_session)

        proposal_out, error = await flow._build_day_change_proposal(
            session, user_id, ai_session, turn
        )
        assert proposal_out is None
        assert error is not None
    del plan_id


# --- _build_pantry_proposal ---------------------------------------------------


async def test_pantry_proposal_creates_pending_proposal(profile_ready, four_real_foods):
    user_id = profile_ready
    candidate = CandidateFood(
        id=four_real_foods["c1"], name_es="Pechuga de pollo (test)",
        kcal_100g=165, protein_100g=31, fat_100g=3.6, carbs_100g=0,
    )
    turn = ChatTurnResult(
        text="",
        day_change_args=None,
        pantry_args={"items": [{"alias": "c1", "approx_quantity_text": "2"}]},
        alias_to_candidate={"c1": candidate},
    )
    async with AdminSessionLocal() as session:
        ai_session = _running_ai_session(user_id, {"source": "text", "text": "tengo dos pechugas"})
        session.add(ai_session)
        await session.commit()
        await session.refresh(ai_session)

        proposal_out = await flow._build_pantry_proposal(session, user_id, ai_session, turn)
        await session.commit()

    assert proposal_out is not None
    assert proposal_out["scope"] == "pantry"
    item = proposal_out["payload"]["items"][0]
    assert item["food_id"] == four_real_foods["c1"]
    assert item["quantity_g"] > 0

    async with AdminSessionLocal() as session:
        proposal = await session.get(AiProposal, uuid.UUID(proposal_out["ai_proposal_id"]))
        assert proposal.status == "pending"
        assert proposal.scope == "pantry"


async def test_pantry_proposal_with_no_resolvable_alias_returns_none(profile_ready):
    user_id = profile_ready
    turn = ChatTurnResult(
        text="",
        day_change_args=None,
        pantry_args={"items": [{"alias": "ghost", "approx_quantity_text": "1"}]},
        alias_to_candidate={},
    )
    async with AdminSessionLocal() as session:
        ai_session = _running_ai_session(user_id, {"source": "text", "text": "algo"})
        session.add(ai_session)
        await session.commit()
        await session.refresh(ai_session)

        result = await flow._build_pantry_proposal(session, user_id, ai_session, turn)
        assert result is None


# --- process_chat_job (end to end del lado worker) ---------------------------


def _fake_turn(**overrides):
    defaults = dict(
        text="Hola, ¿en qué te ayudo?", day_change_args=None, pantry_args=None,
        alias_to_candidate={}, input_tokens=7, output_tokens=4,
    )
    defaults.update(overrides)

    async def _fake_run_chat_turn(session, user_id, token, user_text, history=()):
        return ChatTurnResult(**defaults)

    return _fake_run_chat_turn


async def test_process_chat_job_text_message_succeeds(
    two_users, configured_credential, monkeypatch
):
    user_id, _ = two_users
    monkeypatch.setattr(flow, "run_chat_turn", _fake_turn())
    pushed = {}
    monkeypatch.setattr(flow, "push_chat_result", _fake_push(pushed))

    async with AdminSessionLocal() as session:
        ai_session = _running_ai_session(user_id, {"source": "text", "text": "hola"})
        session.add(ai_session)
        await session.commit()
        await session.refresh(ai_session)
        session_id = ai_session.id

    await flow.process_chat_job(str(session_id))

    reloaded = await _reload_session(session_id)
    assert reloaded.status == "succeeded"
    assert reloaded.response_payload["message"] == "Hola, ¿en qué te ayudo?"
    assert reloaded.input_tokens == 7

    async with AdminSessionLocal() as session:
        messages = (
            await session.scalars(
                select(ChatMessage)
                .where(ChatMessage.user_id == user_id)
                .order_by(ChatMessage.created_at)
            )
        ).all()
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[0].content == "hola"
    assert messages[0].source == "text"
    assert messages[1].content == "Hola, ¿en qué te ayudo?"
    assert pushed["message"] == "Hola, ¿en qué te ayudo?"
    assert pushed.get("proposal") is None


async def test_process_chat_job_saves_voice_message_with_the_already_transcribed_text(
    two_users, configured_credential, monkeypatch
):
    """La transcripción ocurre en el proceso `api` (en memoria); al worker solo
    le llega el texto. Si el worker intentara transcribir, este test revienta."""
    user_id, _ = two_users

    async def _worker_must_never_transcribe(audio_bytes: bytes) -> str:
        raise AssertionError("el worker no debe transcribir: el audio no le llega")

    monkeypatch.setattr(flow, "run_chat_turn", _fake_turn(text="Vale."))
    monkeypatch.setattr(flow, "transcribe", _worker_must_never_transcribe)
    monkeypatch.setattr(flow, "push_chat_result", _fake_push({}))

    async with AdminSessionLocal() as session:
        ai_session = _running_ai_session(
            user_id, {"source": "voice", "text": "dos huevos fritos"}
        )
        session.add(ai_session)
        await session.commit()
        await session.refresh(ai_session)
        session_id = ai_session.id

    await flow.process_chat_job(str(session_id))

    assert (await _reload_session(session_id)).status == "succeeded"
    async with AdminSessionLocal() as session:
        user_message = await session.scalar(
            select(ChatMessage).where(ChatMessage.user_id == user_id, ChatMessage.role == "user")
        )
    assert user_message.content == "dos huevos fritos"
    assert user_message.source == "voice"


def _fake_transcribe(text_out: str, received: dict | None = None):
    async def _fake(audio_bytes: bytes) -> str:
        if received is not None:
            received["audio"] = audio_bytes
        return text_out

    return _fake


async def test_process_chat_job_day_change_propagates_honest_message_on_failure(
    two_users, configured_credential, monkeypatch, low_kcal_food
):
    """Sección 24.3: si la validación falla, el chat responde con un mensaje
    honesto en vez de aplicar nada — no crea ninguna `ai_proposal`."""
    user_id, _ = two_users
    candidate = CandidateFood(
        id=low_kcal_food, name_es="Lechuga (test)", kcal_100g=15,
        protein_100g=1.2, fat_100g=0.2, carbs_100g=2.9,
    )
    monkeypatch.setattr(
        flow,
        "run_chat_turn",
        _fake_turn(
            text="Vale, te bajo la cena a solo lechuga.",
            day_change_args={
                "date": date.today().isoformat(),
                "meals": [
                    {"meal_type": "lunch", "items": [{"alias": "c1", "approx_portion": "large"}]}
                ],
            },
            alias_to_candidate={"c1": candidate},
        ),
    )
    pushed = {}
    monkeypatch.setattr(flow, "push_chat_result", _fake_push(pushed))

    # Sin plan activo -> _build_day_change_proposal devuelve el mensaje
    # honesto "no tienes ningún plan activo".
    async with AdminSessionLocal() as session:
        ai_session = _running_ai_session(
            user_id, {"source": "text", "text": "quítame todo salvo lechuga"}
        )
        session.add(ai_session)
        await session.commit()
        await session.refresh(ai_session)
        session_id = ai_session.id

    await flow.process_chat_job(str(session_id))

    reloaded = await _reload_session(session_id)
    assert reloaded.status == "succeeded"
    assert "ningún plan activo" in reloaded.response_payload["message"]
    assert pushed.get("proposal") is None

    async with AdminSessionLocal() as session:
        proposals = (
            await session.scalars(select(AiProposal).where(AiProposal.ai_session_id == session_id))
        ).all()
    assert proposals == []


async def test_process_chat_job_already_processed_is_a_noop(two_users):
    user_id, _ = two_users
    async with AdminSessionLocal() as session:
        ai_session = _running_ai_session(user_id, {"source": "text", "text": "hola"})
        ai_session.status = "succeeded"
        session.add(ai_session)
        await session.commit()
        await session.refresh(ai_session)
        session_id = ai_session.id

    await flow.process_chat_job(str(session_id))  # no debe reventar

    reloaded = await _reload_session(session_id)
    assert reloaded.status == "succeeded"


# --- request_chat_message (lado api) ------------------------------------------


async def test_request_chat_message_rejects_empty_message(two_users, configured_credential):
    user_id, _ = two_users
    async with AdminSessionLocal() as session:
        with pytest.raises(AppError) as exc_info:
            await flow.request_chat_message(session, user_id, text=None, audio_bytes=None)
        assert exc_info.value.code == "EMPTY_MESSAGE"


async def test_request_chat_message_without_credential_raises(two_users):
    user_id, _ = two_users
    async with AdminSessionLocal() as session:
        await session.execute(text("DELETE FROM ai_credentials"))
        await session.commit()
        with pytest.raises(AppError) as exc_info:
            await flow.request_chat_message(session, user_id, text="hola", audio_bytes=None)
        assert exc_info.value.code == "AI_NOT_CONFIGURED"


async def test_request_chat_message_transcribes_voice_in_memory_and_enqueues_only_text(
    two_users, configured_credential, monkeypatch
):
    """Criterios de la Fase 8: el audio nunca se persiste. Se transcribe en el
    proceso `api` y solo el texto viaja al worker — ni Redis (que vuelca
    snapshots a disco) ni la BD guardan los bytes."""
    import myfood.ai.queue as queue_module

    user_id, _ = two_users
    enqueued = []
    received = {}

    async def _fake_enqueue(session_id: str) -> None:
        enqueued.append(session_id)

    monkeypatch.setattr(flow, "enqueue_chat_job", _fake_enqueue)
    monkeypatch.setattr(flow, "transcribe", _fake_transcribe("dos huevos fritos", received))

    async with AdminSessionLocal() as session:
        ai_session = await flow.request_chat_message(
            session, user_id, text=None, audio_bytes=b"nota de voz falsa"
        )

    assert received["audio"] == b"nota de voz falsa"
    assert ai_session.status == "running"
    assert ai_session.kind == "chat_edit"
    assert ai_session.request_payload == {"source": "voice", "text": "dos huevos fritos"}
    assert enqueued == [str(ai_session.id)]
    # Guarda contra reintroducir el paso del audio por Redis.
    assert not hasattr(queue_module, "store_chat_audio")


async def test_request_chat_message_voice_with_whisper_down_raises_503_and_creates_no_session(
    two_users, configured_credential, monkeypatch
):
    user_id, _ = two_users

    async def _down(audio_bytes: bytes) -> str:
        raise TranscriptionUnavailable("no responde")

    monkeypatch.setattr(flow, "transcribe", _down)
    async with AdminSessionLocal() as session:
        before = await session.scalar(
            text("SELECT count(*) FROM ai_sessions WHERE user_id = :u"), {"u": str(user_id)}
        )
        with pytest.raises(AppError) as exc_info:
            await flow.request_chat_message(session, user_id, text=None, audio_bytes=b"x")
        assert exc_info.value.code == "TRANSCRIPTION_UNAVAILABLE"
        assert exc_info.value.status_code == 503
        after = await session.scalar(
            text("SELECT count(*) FROM ai_sessions WHERE user_id = :u"), {"u": str(user_id)}
        )
    assert after == before


async def test_request_chat_message_rejects_a_voice_note_with_nothing_intelligible(
    two_users, configured_credential, monkeypatch
):
    user_id, _ = two_users
    monkeypatch.setattr(flow, "transcribe", _fake_transcribe("   "))
    async with AdminSessionLocal() as session:
        with pytest.raises(AppError) as exc_info:
            await flow.request_chat_message(session, user_id, text=None, audio_bytes=b"x")
        assert exc_info.value.code == "EMPTY_TRANSCRIPTION"


async def test_request_chat_message_rejects_oversized_audio(two_users, configured_credential):
    user_id, _ = two_users
    oversized = b"x" * (16 * 1024 * 1024)
    async with AdminSessionLocal() as session:
        with pytest.raises(AppError) as exc_info:
            await flow.request_chat_message(session, user_id, text=None, audio_bytes=oversized)
        assert exc_info.value.code == "AUDIO_TOO_LARGE"


# --- transcribe.py -------------------------------------------------------------


async def test_transcribe_raises_when_whisper_unreachable(monkeypatch):
    import httpx

    class _FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, *args, **kwargs):
            raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _FailingClient())

    with pytest.raises(TranscriptionUnavailable):
        await transcribe(b"audio")


# --- HTTP: POST /chat/message, GET/DELETE /chat/history -----------------------


async def _complete_profile_and_login(client):
    await client.put(
        "/api/profile",
        json={"sex": "male", "birth_date": "1990-01-01", "height_cm": 175, "meals_per_day": 3},
    )
    await client.post("/api/consents", json={"kind": "ai_processing", "version": "v1"})


async def test_send_chat_message_returns_message_and_proposal(
    registered_client, monkeypatch
):
    from myfood.chat import router as chat_router

    client, user_id = registered_client
    await _complete_profile_and_login(client)
    async with AdminSessionLocal() as session:
        await ai_client.set_credential(session, admin_user_id=user_id, token="fake-token")

    async def _fake_wait(session_id: str, timeout_seconds: int):
        return {"message": "Hoy llevas 80 g de proteína.", "proposal": None}

    monkeypatch.setattr(chat_router, "wait_for_chat_result", _fake_wait)
    # No hay worker real corriendo en los tests — evita dejar una sesión
    # huérfana en la cola compartida de Redis de desarrollo.
    monkeypatch.setattr(flow, "enqueue_chat_job", _noop_enqueue)

    resp = await client.post("/api/chat/message", data={"text": "¿qué llevo hoy de proteína?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["message"] == "Hoy llevas 80 g de proteína."
    assert body["proposal"] is None

    async with AdminSessionLocal() as session:
        await session.execute(text("DELETE FROM ai_credentials"))
        await session.commit()


async def test_send_chat_message_times_out(registered_client, monkeypatch):
    from myfood.chat import router as chat_router

    client, user_id = registered_client
    await _complete_profile_and_login(client)
    async with AdminSessionLocal() as session:
        await ai_client.set_credential(session, admin_user_id=user_id, token="fake-token")

    async def _fake_wait(session_id: str, timeout_seconds: int):
        return None

    monkeypatch.setattr(chat_router, "wait_for_chat_result", _fake_wait)
    monkeypatch.setattr(flow, "enqueue_chat_job", _noop_enqueue)

    resp = await client.post("/api/chat/message", data={"text": "hola"})
    assert resp.status_code == 504
    assert resp.json()["error"]["code"] == "CHAT_TIMEOUT"

    async with AdminSessionLocal() as session:
        await session.execute(text("DELETE FROM ai_credentials"))
        await session.commit()


async def test_send_chat_message_maps_worker_error_to_503_with_code(
    registered_client, monkeypatch
):
    """Un fallo del worker (p. ej. credencial inválida) llega como 503 con su
    código real — nunca 502/504, que Cloudflare enmascara con su propia
    página (encontrado en vivo)."""
    from myfood.chat import router as chat_router

    client, user_id = registered_client
    await _complete_profile_and_login(client)
    async with AdminSessionLocal() as session:
        await ai_client.set_credential(session, admin_user_id=user_id, token="fake-token")

    async def _fake_wait(session_id: str, timeout_seconds: int):
        return {"error": "AI_CREDENTIAL_INVALID"}

    monkeypatch.setattr(chat_router, "wait_for_chat_result", _fake_wait)
    monkeypatch.setattr(flow, "enqueue_chat_job", _noop_enqueue)

    resp = await client.post("/api/chat/message", data={"text": "hola"})
    assert resp.status_code == 503
    body = resp.json()["error"]
    assert body["code"] == "AI_CREDENTIAL_INVALID"
    assert "renovarla" in body["message"]

    async with AdminSessionLocal() as session:
        await session.execute(text("DELETE FROM ai_credentials"))
        await session.commit()


async def test_send_chat_message_voice_with_whisper_down_is_503_with_a_readable_code(
    registered_client, monkeypatch
):
    client, user_id = registered_client
    await _complete_profile_and_login(client)
    async with AdminSessionLocal() as session:
        await ai_client.set_credential(session, admin_user_id=user_id, token="fake-token")

    async def _down(audio_bytes: bytes) -> str:
        raise TranscriptionUnavailable("no responde")

    monkeypatch.setattr(flow, "transcribe", _down)
    monkeypatch.setattr(flow, "enqueue_chat_job", _noop_enqueue)

    resp = await client.post(
        "/api/chat/message", files={"audio": ("nota.webm", b"audio falso", "audio/webm")}
    )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "TRANSCRIPTION_UNAVAILABLE"

    async with AdminSessionLocal() as session:
        await session.execute(text("DELETE FROM ai_credentials"))
        await session.commit()


async def test_send_chat_message_without_consent_is_forbidden(registered_client):
    client, user_id = registered_client
    async with AdminSessionLocal() as session:
        await ai_client.set_credential(session, admin_user_id=user_id, token="fake-token")

    resp = await client.post("/api/chat/message", data={"text": "hola"})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "AI_CONSENT_REQUIRED"

    async with AdminSessionLocal() as session:
        await session.execute(text("DELETE FROM ai_credentials"))
        await session.commit()


async def test_send_chat_message_rejects_unsupported_audio_type(registered_client):
    client, user_id = registered_client
    await _complete_profile_and_login(client)
    async with AdminSessionLocal() as session:
        await ai_client.set_credential(session, admin_user_id=user_id, token="fake-token")

    resp = await client.post(
        "/api/chat/message",
        files={"audio": ("note.pdf", b"not audio", "application/pdf")},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "UNSUPPORTED_AUDIO_TYPE"

    async with AdminSessionLocal() as session:
        await session.execute(text("DELETE FROM ai_credentials"))
        await session.commit()


async def test_chat_history_round_trip(registered_client):
    """GET/DELETE /chat/history operan sobre `chat_messages` directamente
    — se insertan a mano (vía ORM) en vez de pasar por todo el pipeline del
    chat, que ya está cubierto por los tests de `process_chat_job`."""
    from datetime import UTC, datetime, timedelta

    client, user_id = registered_client
    now = datetime.now(UTC)
    async with AdminSessionLocal() as session:
        session.add(
            ChatMessage(
                user_id=user_id, role="user", content="hola", source="text", created_at=now
            )
        )
        session.add(
            ChatMessage(
                user_id=user_id,
                role="assistant",
                content="¡Hola!",
                source="text",
                created_at=now + timedelta(seconds=1),
            )
        )
        await session.commit()

    resp = await client.get("/api/chat/history")
    assert resp.status_code == 200
    history = resp.json()
    assert len(history) == 2
    # Más reciente primero (sección 7.9).
    assert history[0]["content"] == "¡Hola!"
    assert history[1]["content"] == "hola"

    resp = await client.delete("/api/chat/history")
    assert resp.status_code == 204
    resp = await client.get("/api/chat/history")
    assert resp.json() == []


# --- historial de conversación (encontrado en la primera prueba real) ---------


def test_prompt_without_history_is_just_the_message():
    assert build_chat_user_prompt("hola") == "hola"


def test_prompt_with_history_includes_it_oldest_first_and_marks_current_message():
    prompt = build_chat_user_prompt(
        "el de lata",
        [("user", "cámbiame la cena, tengo salmón"), ("assistant", "¿Cuál de estos salmones?")],
    )
    assert prompt.index("Usuario: cámbiame la cena") < prompt.index("Asistente: ¿Cuál")
    assert prompt.endswith("Mensaje actual del usuario (responde a este):\nel de lata")


def test_prompt_truncates_very_long_history_items():
    prompt = build_chat_user_prompt("x", [("assistant", "a" * 5000)])
    assert "a" * 1500 in prompt
    assert "a" * 1501 not in prompt


async def test_process_chat_job_passes_recent_history_but_not_the_current_message(
    two_users, configured_credential, monkeypatch
):
    from datetime import UTC, datetime, timedelta

    user_id, _ = two_users
    captured = {}

    async def _capturing_turn(session, user_id, token, user_text, history=()):
        captured["history"] = list(history)
        captured["user_text"] = user_text
        return ChatTurnResult(text="ok", day_change_args=None, pantry_args=None)

    monkeypatch.setattr(flow, "run_chat_turn", _capturing_turn)
    monkeypatch.setattr(flow, "push_chat_result", _fake_push({}))

    now = datetime.now(UTC)
    async with AdminSessionLocal() as session:
        session.add_all(
            [
                # Demasiado viejo (fuera de la ventana de contexto): no debe pasar.
                ChatMessage(user_id=user_id, role="user", content="de ayer", source="text",
                            created_at=now - timedelta(hours=30)),
                ChatMessage(user_id=user_id, role="user", content="cámbiame la cena",
                            source="text", created_at=now - timedelta(minutes=5)),
                ChatMessage(user_id=user_id, role="assistant", content="¿cuál salmón?",
                            source="text", created_at=now - timedelta(minutes=4)),
            ]
        )
        ai_session = _running_ai_session(user_id, {"source": "text", "text": "el de lata"})
        session.add(ai_session)
        await session.commit()
        await session.refresh(ai_session)
        session_id = ai_session.id

    await flow.process_chat_job(str(session_id))

    assert captured["user_text"] == "el de lata"
    assert captured["history"] == [
        ("user", "cámbiame la cena"),
        ("assistant", "¿cuál salmón?"),
    ]


# --- read_plan_day devuelve alias reutilizables ---------------------------------


async def _seed_day_meals(plan_id, food_ids_by_meal):
    async with AdminSessionLocal() as session:
        day_id = (
            await session.execute(
                text("SELECT id FROM plan_days WHERE plan_id = :p AND day_index = 0"),
                {"p": str(plan_id)},
            )
        ).scalar_one()
        for order, (meal_type, items) in enumerate(food_ids_by_meal.items()):
            meal_id = uuid.uuid4()
            await session.execute(
                text(
                    "INSERT INTO plan_meals (id, plan_day_id, meal_type, sort_order) "
                    "VALUES (:id, :d, :t, :o)"
                ),
                {"id": str(meal_id), "d": str(day_id), "t": meal_type, "o": order},
            )
            for food_id, grams in items:
                await session.execute(
                    text(
                        "INSERT INTO plan_items (id, plan_meal_id, food_id, grams) "
                        "VALUES (:id, :m, :f, :g)"
                    ),
                    {"id": str(uuid.uuid4()), "m": str(meal_id), "f": str(food_id), "g": grams},
                )
        await session.commit()


async def test_read_plan_day_returns_reusable_aliases_and_never_real_ids(
    active_plan, four_real_foods
):
    import json

    plan_id, user_id = active_plan
    await _seed_day_meals(
        plan_id,
        {
            "lunch": [(four_real_foods["c1"], 150), (four_real_foods["c2"], 200)],
            "dinner": [(four_real_foods["c1"], 120)],  # el mismo alimento en dos comidas
        },
    )
    alias_map: dict = {}
    async with AdminSessionLocal() as session:
        tools = build_chat_tools(
            session, user_id, alias_map=alias_map, day_change_sink=[], pantry_sink=[]
        )
        read_plan_day = next(t for t in tools if t.name == "read_plan_day")
        result = await read_plan_day.handler({"date": date.today().isoformat()})

    body = json.loads(result["content"][0]["text"])
    lunch = body["meals"]["lunch"]
    dinner = body["meals"]["dinner"]
    assert {item["name"] for item in lunch} == {
        "Pechuga de pollo (test)",
        "Arroz blanco cocido (test)",
    }
    # Mismo alimento -> mismo alias en las dos comidas, sin duplicados en el mapa.
    chicken_in_lunch = next(i for i in lunch if i["name"].startswith("Pechuga"))
    assert chicken_in_lunch["alias"] == dinner[0]["alias"]
    assert len(alias_map) == 2
    # El alias resuelve al alimento real, pero el id real nunca sale hacia el modelo (R5).
    assert alias_map[chicken_in_lunch["alias"]].id == four_real_foods["c1"]
    assert four_real_foods["c1"] not in result["content"][0]["text"]


async def test_day_change_is_refused_when_the_day_has_a_batch_cooking_recipe(
    active_plan, four_real_foods
):
    """Aprobar un cambio de día sustituye todas sus comidas: la receta de
    batch cooking no se puede referenciar por alias y se perdería."""
    plan_id, user_id = active_plan
    await _seed_day_meals(plan_id, {"lunch": [(four_real_foods["c1"], 150)]})
    recipe_id = uuid.uuid4()
    async with AdminSessionLocal() as session:
        await session.execute(
            text(
                "INSERT INTO recipes (id, user_id, name, servings) "
                "VALUES (:id, :u, 'Lentejas (test)', 4)"
            ),
            {"id": str(recipe_id), "u": str(user_id)},
        )
        meal_id = (
            await session.execute(
                text(
                    "SELECT pm.id FROM plan_meals pm JOIN plan_days pd ON pd.id = pm.plan_day_id "
                    "WHERE pd.plan_id = :p AND pm.meal_type = 'lunch'"
                ),
                {"p": str(plan_id)},
            )
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO plan_items (id, plan_meal_id, recipe_id, grams, is_substitutable) "
                "VALUES (:id, :m, :r, 300, false)"
            ),
            {"id": str(uuid.uuid4()), "m": str(meal_id), "r": str(recipe_id)},
        )
        await session.commit()

    candidate = CandidateFood(
        id=four_real_foods["c1"], name_es="Pechuga de pollo (test)", kcal_100g=165,
        protein_100g=31, fat_100g=3.6, carbs_100g=0,
    )
    turn = ChatTurnResult(
        text="",
        day_change_args={
            "date": date.today().isoformat(),
            "meals": [
                {"meal_type": "lunch", "items": [{"alias": "c1", "approx_portion": "medium"}]}
            ],
        },
        pantry_args=None,
        alias_to_candidate={"c1": candidate},
    )
    async with AdminSessionLocal() as session:
        ai_session = _running_ai_session(user_id, {"source": "text", "text": "cambia la comida"})
        session.add(ai_session)
        await session.commit()
        await session.refresh(ai_session)
        proposal_out, error = await flow._build_day_change_proposal(
            session, user_id, ai_session, turn
        )
        assert proposal_out is None
        assert "batch cooking" in error
        await session.execute(
            text("DELETE FROM plan_items WHERE recipe_id = :r"), {"r": str(recipe_id)}
        )
        await session.execute(text("DELETE FROM recipes WHERE id = :r"), {"r": str(recipe_id)})
        await session.commit()


def test_system_prompt_forbids_leaking_aliases_and_claiming_changes_are_applied():
    """Encontrado en las pruebas reales: el modelo decía «(c15)» al usuario y
    «He movido el pollo a la cena» cuando solo había una propuesta pendiente."""
    from myfood.ai.prompts import CHAT_SYSTEM_V1

    assert "Nunca menciones los alias internos" in CHAT_SYSTEM_V1
    assert "Tú solo PROPONES" in CHAT_SYSTEM_V1
    assert "Nunca digas que ya has cambiado" in CHAT_SYSTEM_V1
