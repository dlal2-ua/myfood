"""Micronutrientes completos (Fase 7) — GET /log/micronutrients."""

from datetime import date

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def iron_rich_food(superuser_conn):
    """20 mg de hierro / 100 g — muy por encima de cualquier alimento real,
    a propósito, para que el test sea determinista sin depender de qué
    valores exactos tenga el catálogo real cargado en este entorno."""
    import uuid

    food_id = uuid.uuid4()
    await superuser_conn.execute(
        text(
            "INSERT INTO foods (id, kind, source, source_id, license, name_es, quality_rank) "
            "VALUES (:id, 'generic', 'test', :sid, 'CC0', 'Alimento rico en hierro (test)', 1)"
        ),
        {"id": str(food_id), "sid": str(food_id)},
    )
    await superuser_conn.execute(
        text(
            "INSERT INTO food_nutrients "
            "(food_id, kcal_100g, protein_100g, fat_100g, carbs_100g, micros) "
            "VALUES (:id, 100, 5, 1, 10, '{\"iron_mg\": 20, \"vitamin_c_mg\": 50}'::jsonb)"
        ),
        {"id": str(food_id)},
    )
    await superuser_conn.commit()
    yield food_id
    await superuser_conn.execute(
        text("DELETE FROM food_log WHERE food_id = :id"), {"id": str(food_id)}
    )
    await superuser_conn.execute(text("DELETE FROM foods WHERE id = :id"), {"id": str(food_id)})
    await superuser_conn.commit()


async def test_micronutrients_empty_day_returns_zero_amounts(registered_client):
    client, _ = registered_client
    resp = await client.get("/api/log/micronutrients", params={"date": date.today().isoformat()})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["nutrients"]) == 17  # los 17 micros curados del ETL
    iron = next(n for n in body["nutrients"] if n["key"] == "iron_mg")
    assert iron["amount"] == 0.0
    assert iron["reference"] > 0
    assert iron["pct_of_reference"] == 0.0


async def test_micronutrients_sums_real_entries_and_computes_pct(
    registered_client, iron_rich_food
):
    client, _ = registered_client
    await client.put("/api/profile", json={"sex": "male"})
    today = date.today().isoformat()

    # 200 g -> 40 mg de hierro (referencia masculina: 11 mg -> ~364%)
    resp = await client.post(
        "/api/log/food",
        json={
            "log_date": today,
            "meal_type": "lunch",
            "food_id": str(iron_rich_food),
            "grams": 200,
        },
    )
    assert resp.status_code == 201

    micros = await client.get("/api/log/micronutrients", params={"date": today})
    assert micros.status_code == 200
    iron = next(n for n in micros.json()["nutrients"] if n["key"] == "iron_mg")
    assert iron["amount"] == pytest.approx(40.0)
    assert iron["reference"] == pytest.approx(11.0)
    assert iron["pct_of_reference"] == pytest.approx(363.6, abs=0.5)


async def test_micronutrients_reference_differs_by_sex(registered_client):
    client, _ = registered_client
    today = date.today().isoformat()

    await client.put("/api/profile", json={"sex": "female"})
    female = await client.get("/api/log/micronutrients", params={"date": today})
    female_iron = next(n for n in female.json()["nutrients"] if n["key"] == "iron_mg")

    await client.put("/api/profile", json={"sex": "male"})
    male = await client.get("/api/log/micronutrients", params={"date": today})
    male_iron = next(n for n in male.json()["nutrients"] if n["key"] == "iron_mg")

    assert female_iron["reference"] > male_iron["reference"]


async def test_micronutrients_only_counts_the_requested_day(registered_client, iron_rich_food):
    client, _ = registered_client
    await client.post(
        "/api/log/food",
        json={
            "log_date": "2020-01-01",
            "meal_type": "lunch",
            "food_id": str(iron_rich_food),
            "grams": 100,
        },
    )
    resp = await client.get("/api/log/micronutrients", params={"date": date.today().isoformat()})
    iron = next(n for n in resp.json()["nutrients"] if n["key"] == "iron_mg")
    assert iron["amount"] == 0.0
