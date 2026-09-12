"""Tests del flujo de Smart Log (sección 10.8). `process_smart_log_job`
(la mitad que corre en el `worker`) se prueba construyendo el
`ai_session.request_payload` a mano — igual que en
`test_ai_flow_diet_plan.py` — para no depender de qué haya indexado
Meilisearch en este entorno. `request_smart_log` (la mitad en el proceso
`api`) sí necesita `search_foods`, pero se simula: el índice de Meilisearch
puede estar vacío (CI no ejecuta el ETL) o tener el catálogo real completo
(entorno de desarrollo), y ninguno de los dos debe condicionar si este test
pasa."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from myfood.ai import client as ai_client
from myfood.ai.agent import AgentResult, AiAgentError
from myfood.ai.flows import smart_log as flow
from myfood.db.models import AiSession
from myfood.db.session import AdminSessionLocal
from myfood.errors import AppError


@pytest_asyncio.fixture
async def one_real_food(superuser_conn):
    food_id = uuid.uuid4()
    await superuser_conn.execute(
        text(
            "INSERT INTO foods "
            "(id, kind, source, source_id, license, name_es, quality_rank, serving_size_g) "
            "VALUES (:id, 'generic', 'test', :sid, 'CC0', 'Huevo frito (test)', 1, 60)"
        ),
        {"id": str(food_id), "sid": str(food_id)},
    )
    await superuser_conn.execute(
        text(
            "INSERT INTO food_nutrients "
            "(food_id, kcal_100g, protein_100g, fat_100g, carbs_100g, micros) "
            "VALUES (:id, 196, 14, 15, 0.8, '{}'::jsonb)"
        ),
        {"id": str(food_id)},
    )
    await superuser_conn.commit()
    yield str(food_id)
    await superuser_conn.execute(text("DELETE FROM foods WHERE id = :id"), {"id": str(food_id)})
    await superuser_conn.commit()


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
async def running_smart_log_session(two_users, one_real_food):
    user_id, _ = two_users
    async with AdminSessionLocal() as session:
        ai_session = AiSession(
            user_id=user_id,
            kind="smart_log",
            status="running",
            request_payload={
                "prompt_version": "smart_log_v1",
                "text": "dos huevos fritos",
                "candidates": [
                    {"id": "c1", "name": "Huevo frito (test)", "category": None},
                ],
                "alias_to_food_id": {"c1": one_real_food},
            },
        )
        session.add(ai_session)
        await session.commit()
        await session.refresh(ai_session)
    return ai_session.id


async def _reload(session_id) -> AiSession:
    async with AdminSessionLocal() as session:
        return await session.get(AiSession, session_id)


def _fake_agent_call(items: list[dict]):
    async def _fake_run_agent(
        *, token, prompt, system_prompt, mcp_tools, max_turns, timeout_seconds
    ):
        await mcp_tools[0].handler({"items": items})
        return AgentResult(text="", input_tokens=3, output_tokens=2)

    return _fake_run_agent


# --- process_smart_log_job (worker) -----------------------------------------


async def test_success_path_resolves_alias_to_real_food_with_default_grams(
    running_smart_log_session, one_real_food, configured_credential, monkeypatch
):
    monkeypatch.setattr(
        flow, "run_agent", _fake_agent_call([{"alias": "c1", "approx_quantity_text": "dos"}])
    )

    await flow.process_smart_log_job(str(running_smart_log_session))

    ai_session = await _reload(running_smart_log_session)
    assert ai_session.status == "succeeded"
    assert ai_session.input_tokens == 3
    assert ai_session.output_tokens == 2
    items = ai_session.response_payload["items"]
    assert len(items) == 1
    assert items[0]["food_id"] == one_real_food
    assert items[0]["name_es"] == "Huevo frito (test)"
    assert items[0]["grams"] == 120.0  # 60g de ración x2 ("dos")
    assert items[0]["approx_quantity_text"] == "dos"
    assert ai_session.response_payload["warning"] is None


async def test_unknown_alias_is_silently_dropped_not_invented(
    running_smart_log_session, configured_credential, monkeypatch
):
    monkeypatch.setattr(
        flow, "run_agent", _fake_agent_call([{"alias": "ghost", "approx_quantity_text": "uno"}])
    )

    await flow.process_smart_log_job(str(running_smart_log_session))

    ai_session = await _reload(running_smart_log_session)
    assert ai_session.status == "succeeded"
    assert ai_session.response_payload["items"] == []
    assert ai_session.response_payload["warning"] == "NO_MATCH"


async def test_no_tool_call_still_succeeds_with_no_match_warning(
    running_smart_log_session, configured_credential, monkeypatch
):
    async def _fake_run_agent(
        *, token, prompt, system_prompt, mcp_tools, max_turns, timeout_seconds
    ):
        return AgentResult(text="no encuentro nada parecido", input_tokens=1, output_tokens=1)

    monkeypatch.setattr(flow, "run_agent", _fake_run_agent)

    await flow.process_smart_log_job(str(running_smart_log_session))

    ai_session = await _reload(running_smart_log_session)
    assert ai_session.status == "succeeded"
    assert ai_session.response_payload == {"items": [], "warning": "NO_MATCH"}


async def test_agent_error_marks_session_failed(
    running_smart_log_session, configured_credential, monkeypatch
):
    async def _fake_run_agent(
        *, token, prompt, system_prompt, mcp_tools, max_turns, timeout_seconds
    ):
        raise AiAgentError("boom", code="AI_TIMEOUT")

    monkeypatch.setattr(flow, "run_agent", _fake_run_agent)

    await flow.process_smart_log_job(str(running_smart_log_session))

    ai_session = await _reload(running_smart_log_session)
    assert ai_session.status == "failed"
    assert ai_session.validation_errors[0]["code"] == "AI_TIMEOUT"


async def test_missing_credential_marks_session_failed(running_smart_log_session):
    await flow.process_smart_log_job(str(running_smart_log_session))

    ai_session = await _reload(running_smart_log_session)
    assert ai_session.status == "failed"
    assert ai_session.validation_errors[0]["code"] == "AI_NOT_CONFIGURED"


async def test_already_processed_session_is_left_untouched(
    running_smart_log_session, configured_credential
):
    async with AdminSessionLocal() as session:
        ai_session = await session.get(AiSession, running_smart_log_session)
        ai_session.status = "succeeded"
        await session.commit()

    await flow.process_smart_log_job(str(running_smart_log_session))

    ai_session = await _reload(running_smart_log_session)
    assert ai_session.status == "succeeded"


# --- request_smart_log (api) -------------------------------------------------


async def test_request_raises_ai_not_configured_without_credential(two_users):
    user_id, _ = two_users
    async with AdminSessionLocal() as session:
        await session.execute(text("DELETE FROM ai_credentials"))
        await session.commit()
        with pytest.raises(AppError) as exc_info:
            await flow.request_smart_log(session, user_id, text="dos huevos")
        assert exc_info.value.code == "AI_NOT_CONFIGURED"


async def test_request_raises_no_candidate_foods_when_search_finds_nothing(
    two_users, configured_credential, monkeypatch
):
    user_id, _ = two_users

    async def _fake_search_foods(query, kind, limit, offset):
        return [], 0

    monkeypatch.setattr(flow, "search_foods", _fake_search_foods)

    async with AdminSessionLocal() as session:
        with pytest.raises(AppError) as exc_info:
            await flow.request_smart_log(session, user_id, text="algo muy raro")
    assert exc_info.value.code == "NO_CANDIDATE_FOODS"


async def test_request_creates_running_session_and_enqueues_job(
    two_users, configured_credential, monkeypatch
):
    user_id, _ = two_users

    async def _fake_search_foods(query, kind, limit, offset):
        return [
            {"id": "11111111-1111-1111-1111-111111111111", "name_es": "Huevo", "category": None}
        ], 1

    enqueued = []

    async def _fake_enqueue(ai_session_id: str) -> None:
        enqueued.append(ai_session_id)

    monkeypatch.setattr(flow, "search_foods", _fake_search_foods)
    monkeypatch.setattr(flow, "enqueue_smart_log_job", _fake_enqueue)

    async with AdminSessionLocal() as session:
        ai_session = await flow.request_smart_log(session, user_id, text="un huevo")

    assert ai_session.status == "running"
    assert ai_session.kind == "smart_log"
    payload = ai_session.request_payload
    assert payload["text"] == "un huevo"
    assert payload["candidates"] == [{"id": "c1", "name": "Huevo", "category": None}]
    assert payload["alias_to_food_id"] == {"c1": "11111111-1111-1111-1111-111111111111"}
    assert enqueued == [str(ai_session.id)]
