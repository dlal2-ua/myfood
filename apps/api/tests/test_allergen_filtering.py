"""Filtro de alérgenos de extremo a extremo.

Criterio de aceptación de la Fase 4: «Nunca incluye un alimento con un
alérgeno del usuario (test explícito)». Hasta ahora los tests de exclusión
usaban `banned_food` (un `food_id` concreto), y `food_allergens` estaba vacía
en producción: el camino real de una alergia — restricción `allergen` ->
`food_allergens` -> exclusión — no lo cubría ningún test ni tenía datos."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from myfood.ai.validator import validate_structure
from myfood.chat.tools import build_chat_tools
from myfood.db.session import AdminSessionLocal
from myfood.domain.food_candidates import select_candidates

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def gluten_foods(diet_candidates, superuser_conn):
    """Los dos alimentos más 'competitivos' del pool de `diet_candidates`
    (súper-proteína y súper-carbohidrato, los que el solver más querría usar)
    marcados como alérgenos: uno declarado y otro inferido."""
    tagged = {"declared": diet_candidates[0], "inferred": diet_candidates[1]}
    for origin, food_id in tagged.items():
        await superuser_conn.execute(
            text(
                "INSERT INTO food_allergens (food_id, allergen_code, origin) "
                "VALUES (:id, 'gluten', :origin)"
            ),
            {"id": str(food_id), "origin": origin},
        )
    await superuser_conn.commit()
    yield tagged
    await superuser_conn.execute(
        text("DELETE FROM food_allergens WHERE food_id = ANY(:ids)"),
        {"ids": [str(f) for f in tagged.values()]},
    )
    await superuser_conn.commit()


async def _complete_profile(client):
    await client.put(
        "/api/profile",
        json={"sex": "male", "birth_date": "1995-01-01", "height_cm": 180, "meals_per_day": 3},
    )
    await client.post("/api/measurements", json={"measured_on": "2026-01-10", "weight_kg": 80})


async def _restrict(client, kind: str, code: str = "gluten"):
    resp = await client.post("/api/restrictions", json={"kind": kind, "allergen_code": code})
    assert resp.status_code == 201


async def _candidate_ids(user_id) -> set[str]:
    async with AdminSessionLocal() as session:
        return {c.id for c in await select_candidates(session, user_id)}


async def test_without_the_restriction_the_tagged_foods_are_normal_candidates(
    registered_client, gluten_foods
):
    """Control: el etiquetado por sí solo no excluye nada — es la restricción del
    usuario la que lo hace (si no, los otros tests no probarían el filtro)."""
    _client, user_id = registered_client
    ids = await _candidate_ids(user_id)
    assert {str(f) for f in gluten_foods.values()} <= ids


@pytest.mark.parametrize("kind", ["allergen", "intolerance"])
async def test_allergen_or_intolerance_keeps_tagged_foods_out_of_the_candidate_pool(
    registered_client, gluten_foods, kind
):
    client, user_id = registered_client
    await _restrict(client, kind)
    ids = await _candidate_ids(user_id)
    for food_id in gluten_foods.values():
        assert str(food_id) not in ids


@pytest.mark.parametrize("kind", ["allergen", "intolerance"])
async def test_a_generated_plan_never_contains_a_food_with_the_users_allergen(
    registered_client, gluten_foods, kind
):
    client, _user_id = registered_client
    await _complete_profile(client)
    await _restrict(client, kind)

    resp = await client.post("/api/diet-plans/generate", json={"num_days": 3})
    assert resp.status_code == 201
    used = {
        item["food_id"]
        for day in resp.json()["days"]
        for meal in day["meals"]
        for item in meal["items"]
    }
    assert used, "el plan no debería salir vacío"
    for food_id in gluten_foods.values():
        assert str(food_id) not in used


async def test_trace_origin_also_counts_for_an_allergy(
    registered_client, diet_candidates, superuser_conn
):
    """«Puede contener trazas de gluten» es motivo de exclusión para un celíaco."""
    client, user_id = registered_client
    food_id = diet_candidates[2]
    await superuser_conn.execute(
        text(
            "INSERT INTO food_allergens (food_id, allergen_code, origin) "
            "VALUES (:id, 'gluten', 'trace')"
        ),
        {"id": str(food_id)},
    )
    await superuser_conn.commit()
    try:
        assert str(food_id) in await _candidate_ids(user_id)
        await _restrict(client, "allergen")
        assert str(food_id) not in await _candidate_ids(user_id)
    finally:
        await superuser_conn.execute(
            text("DELETE FROM food_allergens WHERE food_id = :id"), {"id": str(food_id)}
        )
        await superuser_conn.commit()


async def test_a_restriction_on_one_allergen_does_not_exclude_foods_tagged_with_another(
    registered_client, gluten_foods
):
    client, user_id = registered_client
    await _restrict(client, "allergen", "lacteos")
    ids = await _candidate_ids(user_id)
    for food_id in gluten_foods.values():
        assert str(food_id) in ids


async def test_the_iafood_validator_rejects_a_proposal_containing_the_users_allergen(
    registered_client, gluten_foods
):
    client, user_id = registered_client
    await _restrict(client, "allergen")
    tagged = str(gluten_foods["declared"])

    plan_args = {
        "days": [{"day_index": 0, "meals": [{"meal_type": "lunch", "items": [{"alias": "c1"}]}]}]
    }
    async with AdminSessionLocal() as session:
        errors, _resolved = await validate_structure(
            session,
            plan_args,
            alias_to_food_id={"c1": tagged},
            user_id=user_id,
            expected_num_days=1,
            expected_meal_types=["lunch"],
        )
    assert "RESTRICTED_FOOD_SELECTED" in {e.code for e in errors}


async def test_chat_food_search_never_offers_the_users_allergen(
    registered_client, gluten_foods, monkeypatch
):
    client, user_id = registered_client
    await _restrict(client, "allergen")
    tagged = str(gluten_foods["declared"])
    safe = str(await _safe_food_id())

    async def _fake_meili(query, kind, limit, offset):
        return [{"id": tagged}, {"id": safe}], 2

    monkeypatch.setattr("myfood.chat.tools.meili_search_foods", _fake_meili)

    alias_map: dict = {}
    async with AdminSessionLocal() as session:
        tools = build_chat_tools(
            session, user_id, alias_map=alias_map, day_change_sink=[], pantry_sink=[]
        )
        search = next(t for t in tools if t.name == "search_foods")
        await search.handler({"query": "cualquier cosa"})

    offered = {c.id for c in alias_map.values()}
    assert tagged not in offered
    assert safe in offered


async def _safe_food_id():
    """Un alimento sin etiquetas de alérgenos, creado al vuelo."""
    food_id = uuid.uuid4()
    async with AdminSessionLocal() as session:
        await session.execute(
            text(
                "INSERT INTO foods (id, kind, source, source_id, license, name_es, quality_rank) "
                "VALUES (:id, 'generic', 'test', :sid, 'CC0', 'Arroz sin alérgenos (test)', 1)"
            ),
            {"id": str(food_id), "sid": str(food_id)},
        )
        await session.execute(
            text(
                "INSERT INTO food_nutrients (food_id, kcal_100g, protein_100g, fat_100g, "
                "carbs_100g, micros) VALUES (:id, 130, 2.7, 0.3, 28, '{}'::jsonb)"
            ),
            {"id": str(food_id)},
        )
        await session.commit()
    _CLEANUP.append(food_id)
    return food_id


_CLEANUP: list[uuid.UUID] = []


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_safe_foods():
    yield
    if _CLEANUP:
        async with AdminSessionLocal() as session:
            await session.execute(
                text("DELETE FROM foods WHERE id = ANY(:ids)"), {"ids": [str(i) for i in _CLEANUP]}
            )
            await session.commit()
        _CLEANUP.clear()


async def test_food_detail_lists_allergens_with_their_origin(registered_client, gluten_foods):
    client, _user_id = registered_client

    declared = await client.get(f"/api/foods/{gluten_foods['declared']}")
    assert declared.status_code == 200
    listed = declared.json()["allergens"]
    assert [(a["code"], a["origin"]) for a in listed] == [("gluten", "declared")]
    assert listed[0]["name_es"]

    inferred = await client.get(f"/api/foods/{gluten_foods['inferred']}")
    assert [a["origin"] for a in inferred.json()["allergens"]] == ["inferred"]
