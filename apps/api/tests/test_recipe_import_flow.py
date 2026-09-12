"""Tests del flujo de importación de recetas desde URL (sección 20).

`process_recipe_import_job` se prueba SIN red real: `_fetch_html` se
simula devolviendo HTML sintético con un bloque JSON-LD schema.org/Recipe
construido a mano (misma estrategia ya usada para verificar
`recipe_scrapers` — depender de un sitio externo real, como se comprobó
con allrecipes.com devolviendo 403 por bloqueo de bots, habría hecho estos
tests frágiles por motivos ajenos al código). La resolución de cada línea
de ingrediente se simula igual que en `test_smart_log_flow.py`, porque
reutiliza el mismo `ai/flows/food_resolution.py`."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from myfood.ai import client as ai_client
from myfood.ai.agent import AgentResult, AiAgentError
from myfood.ai.flows import food_resolution
from myfood.ai.flows import recipe_import as flow
from myfood.db.models import AiSession
from myfood.db.session import AdminSessionLocal
from myfood.errors import AppError

pytestmark = pytest.mark.asyncio

_SYNTHETIC_RECIPE_HTML = """
<html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Recipe",
  "name": "Tortilla de patatas de prueba",
  "recipeYield": "4 servings",
  "totalTime": "PT30M",
  "recipeIngredient": ["dos huevos", "una patata"],
  "recipeInstructions": "Bate los huevos. Fríe la patata. Mezcla y cuaja."
}
</script>
</head><body></body></html>
"""

_HTML_WITHOUT_SCHEMA = "<html><head></head><body><p>Esto no es una receta.</p></body></html>"


@pytest_asyncio.fixture
async def one_real_food(superuser_conn):
    food_id = uuid.uuid4()
    await superuser_conn.execute(
        text(
            "INSERT INTO foods "
            "(id, kind, source, source_id, license, name_es, quality_rank, serving_size_g) "
            "VALUES (:id, 'generic', 'test', :sid, 'CC0', 'Huevo (test)', 1, 60)"
        ),
        {"id": str(food_id), "sid": str(food_id)},
    )
    await superuser_conn.execute(
        text(
            "INSERT INTO food_nutrients "
            "(food_id, kcal_100g, protein_100g, fat_100g, carbs_100g, micros) "
            "VALUES (:id, 155, 13, 11, 1.1, '{}'::jsonb)"
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
async def running_recipe_import_session(two_users):
    user_id, _ = two_users
    async with AdminSessionLocal() as session:
        ai_session = AiSession(
            user_id=user_id,
            kind="recipe_import",
            status="running",
            request_payload={
                "prompt_version": "recipe_import_v1",
                "url": "http://8.8.8.8/recipe",
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


def _fake_search_foods_always_hits(food_id: str, name: str):
    async def _fake(query, kind, limit, offset):
        return [{"id": food_id, "name_es": name, "category": None}], 1

    return _fake


# --- process_recipe_import_job (worker) -------------------------------------


async def test_success_path_builds_draft_recipe_from_all_ingredient_lines(
    running_recipe_import_session, one_real_food, configured_credential, monkeypatch
):
    monkeypatch.setattr(flow, "_fetch_html", _fake_fetch(_SYNTHETIC_RECIPE_HTML))
    monkeypatch.setattr(
        food_resolution,
        "search_foods",
        _fake_search_foods_always_hits(one_real_food, "Huevo (test)"),
    )
    monkeypatch.setattr(
        food_resolution,
        "run_agent",
        _fake_agent_call([{"alias": "c1", "approx_quantity_text": "dos"}]),
    )

    await flow.process_recipe_import_job(str(running_recipe_import_session))

    ai_session = await _reload(running_recipe_import_session)
    assert ai_session.status == "succeeded"
    payload = ai_session.response_payload
    assert payload["name"] == "Tortilla de patatas de prueba"
    assert payload["servings"] == 4
    assert payload["prep_minutes"] == 30
    assert "Bate los huevos" in payload["instructions"]
    assert len(payload["ingredients"]) == 2
    assert payload["unresolved_lines"] == []
    first = payload["ingredients"][0]
    assert first["food_id"] == one_real_food
    assert first["grams"] == 120.0  # 60g de ración x2 ("dos")
    assert first["original_line"] == "dos huevos"
    assert ai_session.input_tokens == 6  # 3 por línea x 2 líneas
    assert ai_session.output_tokens == 4


async def test_line_with_no_candidates_ends_up_unresolved(
    running_recipe_import_session, one_real_food, configured_credential, monkeypatch
):
    async def _fake_search_foods(query, kind, limit, offset):
        if "patata" in query:
            return [], 0
        return [{"id": one_real_food, "name_es": "Huevo (test)", "category": None}], 1

    monkeypatch.setattr(flow, "_fetch_html", _fake_fetch(_SYNTHETIC_RECIPE_HTML))
    monkeypatch.setattr(food_resolution, "search_foods", _fake_search_foods)
    monkeypatch.setattr(
        food_resolution,
        "run_agent",
        _fake_agent_call([{"alias": "c1", "approx_quantity_text": "dos"}]),
    )

    await flow.process_recipe_import_job(str(running_recipe_import_session))

    ai_session = await _reload(running_recipe_import_session)
    assert ai_session.status == "succeeded"
    payload = ai_session.response_payload
    assert len(payload["ingredients"]) == 1
    assert payload["unresolved_lines"] == ["una patata"]


async def test_no_schema_found_marks_session_failed(
    running_recipe_import_session, configured_credential, monkeypatch
):
    monkeypatch.setattr(flow, "_fetch_html", _fake_fetch(_HTML_WITHOUT_SCHEMA))

    await flow.process_recipe_import_job(str(running_recipe_import_session))

    ai_session = await _reload(running_recipe_import_session)
    assert ai_session.status == "failed"
    assert ai_session.validation_errors[0]["code"] == "RECIPE_SCHEMA_NOT_FOUND"


async def test_fetch_failure_marks_session_failed(
    running_recipe_import_session, configured_credential, monkeypatch
):
    async def _raise_fetch_failed(url):
        raise AppError("RECIPE_FETCH_FAILED", "boom", status_code=422)

    monkeypatch.setattr(flow, "_fetch_html", _raise_fetch_failed)

    await flow.process_recipe_import_job(str(running_recipe_import_session))

    ai_session = await _reload(running_recipe_import_session)
    assert ai_session.status == "failed"
    assert ai_session.validation_errors[0]["code"] == "RECIPE_FETCH_FAILED"


async def test_unsafe_url_at_worker_time_marks_session_failed(two_users):
    """Segunda comprobación SSRF (TOCTOU) — si la sesión llegó con una URL
    que ya no resuelve a una IP pública, el worker la rechaza igual sin
    necesidad de llegar a intentar la descarga."""
    user_id, _ = two_users
    async with AdminSessionLocal() as session:
        ai_session = AiSession(
            user_id=user_id,
            kind="recipe_import",
            status="running",
            request_payload={"prompt_version": "recipe_import_v1", "url": "http://127.0.0.1/x"},
        )
        session.add(ai_session)
        await session.commit()
        await session.refresh(ai_session)
        session_id = ai_session.id

    await flow.process_recipe_import_job(str(session_id))

    ai_session = await _reload(session_id)
    assert ai_session.status == "failed"
    assert ai_session.validation_errors[0]["code"] == "UNSAFE_URL"


async def test_missing_credential_marks_session_failed(running_recipe_import_session, monkeypatch):
    monkeypatch.setattr(flow, "_fetch_html", _fake_fetch(_SYNTHETIC_RECIPE_HTML))

    await flow.process_recipe_import_job(str(running_recipe_import_session))

    ai_session = await _reload(running_recipe_import_session)
    assert ai_session.status == "failed"
    assert ai_session.validation_errors[0]["code"] == "AI_NOT_CONFIGURED"


async def test_agent_error_marks_session_failed(
    running_recipe_import_session, one_real_food, configured_credential, monkeypatch
):
    async def _fake_run_agent(
        *, token, prompt, system_prompt, mcp_tools, max_turns, timeout_seconds
    ):
        raise AiAgentError("boom", code="AI_TIMEOUT")

    monkeypatch.setattr(flow, "_fetch_html", _fake_fetch(_SYNTHETIC_RECIPE_HTML))
    monkeypatch.setattr(
        food_resolution,
        "search_foods",
        _fake_search_foods_always_hits(one_real_food, "Huevo (test)"),
    )
    monkeypatch.setattr(food_resolution, "run_agent", _fake_run_agent)

    await flow.process_recipe_import_job(str(running_recipe_import_session))

    ai_session = await _reload(running_recipe_import_session)
    assert ai_session.status == "failed"
    assert ai_session.validation_errors[0]["code"] == "AI_TIMEOUT"


async def test_already_processed_session_is_left_untouched(
    running_recipe_import_session, configured_credential
):
    async with AdminSessionLocal() as session:
        ai_session = await session.get(AiSession, running_recipe_import_session)
        ai_session.status = "succeeded"
        await session.commit()

    await flow.process_recipe_import_job(str(running_recipe_import_session))

    ai_session = await _reload(running_recipe_import_session)
    assert ai_session.status == "succeeded"


def _fake_fetch(html: str):
    async def _fetch(url: str) -> str:
        return html

    return _fetch


# --- request_recipe_import (api) --------------------------------------------


async def test_request_raises_ai_not_configured_without_credential(two_users):
    user_id, _ = two_users
    async with AdminSessionLocal() as session:
        await session.execute(text("DELETE FROM ai_credentials"))
        await session.commit()
        with pytest.raises(AppError) as exc_info:
            await flow.request_recipe_import(session, user_id, url="http://8.8.8.8/recipe")
        assert exc_info.value.code == "AI_NOT_CONFIGURED"


async def test_request_rejects_unsafe_url(two_users, configured_credential):
    user_id, _ = two_users
    async with AdminSessionLocal() as session:
        with pytest.raises(AppError) as exc_info:
            await flow.request_recipe_import(session, user_id, url="http://127.0.0.1/x")
        assert exc_info.value.code == "UNSAFE_URL"


async def test_request_creates_running_session_and_enqueues_job(
    two_users, configured_credential, monkeypatch
):
    user_id, _ = two_users
    enqueued = []

    async def _fake_enqueue(ai_session_id: str) -> None:
        enqueued.append(ai_session_id)

    monkeypatch.setattr(flow, "enqueue_recipe_import_job", _fake_enqueue)

    async with AdminSessionLocal() as session:
        ai_session = await flow.request_recipe_import(session, user_id, url="http://8.8.8.8/recipe")

    assert ai_session.status == "running"
    assert ai_session.kind == "recipe_import"
    assert ai_session.request_payload["url"] == "http://8.8.8.8/recipe"
    assert enqueued == [str(ai_session.id)]
