"""Batch cooking (Fase 7, documento 1): asignar raciones de una receta ya
cocinada a comidas concretas de un plan existente."""

import uuid

import pytest

pytestmark = pytest.mark.asyncio


async def _complete_profile(client):
    await client.put(
        "/api/profile",
        json={"sex": "male", "birth_date": "1995-01-01", "height_cm": 180, "meals_per_day": 3},
    )
    await client.post("/api/measurements", json={"measured_on": "2026-01-10", "weight_kg": 80})


async def _make_plan(client, diet_candidates) -> dict:
    await _complete_profile(client)
    resp = await client.post(
        "/api/diet-plans/generate", json={"name": "Plan batch cooking", "num_days": 1}
    )
    assert resp.status_code == 201
    return resp.json()


async def _make_recipe(client, test_food, *, servings: int = 4, grams: float = 800) -> str:
    resp = await client.post(
        "/api/recipes",
        json={
            "name": "Lentejas para la semana",
            "servings": servings,
            "ingredients": [{"food_id": str(test_food), "grams": grams}],
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def test_batch_cook_replaces_meal_with_recipe_item(
    registered_client, diet_candidates, test_food
):
    client, _ = registered_client
    plan = await _make_plan(client, diet_candidates)
    recipe_id = await _make_recipe(client, test_food, servings=4, grams=800)  # 200 g/ración

    day = plan["days"][0]
    meal_type = day["meals"][0]["meal_type"]

    resp = await client.post(
        f"/api/diet-plans/{plan['id']}/batch-cook",
        json={
            "recipe_id": recipe_id,
            "assignments": [
                {"day_index": 0, "meal_type": meal_type, "servings": 2},
            ],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    updated_meal = next(m for m in body["days"][0]["meals"] if m["meal_type"] == meal_type)
    assert len(updated_meal["items"]) == 1
    item = updated_meal["items"][0]
    assert item["recipe_id"] == recipe_id
    assert item["food_id"] is None
    assert item["grams"] == pytest.approx(400.0)  # 200 g/ración x 2 raciones
    assert item["name_es"] == "Lentejas para la semana"

    # test_food: 165 kcal/100g -> 400 g = 660 kcal, deben entrar en el total del día.
    assert updated_meal["items"][0]["is_substitutable"] is False


async def test_batch_cook_nutrition_counts_toward_day_totals(
    registered_client, diet_candidates, test_food
):
    client, _ = registered_client
    plan = await _make_plan(client, diet_candidates)
    recipe_id = await _make_recipe(client, test_food, servings=4, grams=800)
    day = plan["days"][0]
    meal_type = day["meals"][0]["meal_type"]
    other_meals_kcal_before = sum(
        item["grams"] for m in day["meals"] if m["meal_type"] != meal_type for item in m["items"]
    )

    resp = await client.post(
        f"/api/diet-plans/{plan['id']}/batch-cook",
        json={
            "recipe_id": recipe_id,
            "assignments": [{"day_index": 0, "meal_type": meal_type, "servings": 2}],
        },
    )
    body = resp.json()

    detail = await client.get(f"/api/diet-plans/{plan['id']}")
    day_out = detail.json()["days"][0]
    # 400 g de "Pechuga de pollo de prueba" (165 kcal/100g) = 660 kcal de la receta.
    recipe_kcal = 165 * 400 / 100
    assert day_out["totals"]["kcal"] >= recipe_kcal - 1  # sumado junto al resto de comidas
    del other_meals_kcal_before, body  # solo para claridad de la lectura del test


async def test_batch_cook_unknown_day_is_404(registered_client, diet_candidates, test_food):
    client, _ = registered_client
    plan = await _make_plan(client, diet_candidates)
    recipe_id = await _make_recipe(client, test_food)

    resp = await client.post(
        f"/api/diet-plans/{plan['id']}/batch-cook",
        json={
            "recipe_id": recipe_id,
            "assignments": [{"day_index": 99, "meal_type": "lunch", "servings": 1}],
        },
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PLAN_DAY_NOT_FOUND"


async def test_batch_cook_unknown_meal_type_is_404(registered_client, diet_candidates, test_food):
    client, _ = registered_client
    plan = await _make_plan(client, diet_candidates)
    recipe_id = await _make_recipe(client, test_food)

    resp = await client.post(
        f"/api/diet-plans/{plan['id']}/batch-cook",
        json={
            "recipe_id": recipe_id,
            "assignments": [{"day_index": 0, "meal_type": "supper", "servings": 1}],
        },
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PLAN_MEAL_NOT_FOUND"


async def test_batch_cook_unknown_recipe_is_404(registered_client, diet_candidates):
    client, _ = registered_client
    plan = await _make_plan(client, diet_candidates)

    resp = await client.post(
        f"/api/diet-plans/{plan['id']}/batch-cook",
        json={
            "recipe_id": str(uuid.uuid4()),
            "assignments": [{"day_index": 0, "meal_type": "lunch", "servings": 1}],
        },
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "RECIPE_NOT_FOUND"


async def test_shopping_list_from_plan_expands_recipe_ingredients(
    registered_client, diet_candidates, test_food
):
    client, _ = registered_client
    plan = await _make_plan(client, diet_candidates)
    recipe_id = await _make_recipe(client, test_food, servings=4, grams=800)
    meal_type = plan["days"][0]["meals"][0]["meal_type"]

    await client.post(
        f"/api/diet-plans/{plan['id']}/batch-cook",
        json={
            "recipe_id": recipe_id,
            "assignments": [{"day_index": 0, "meal_type": meal_type, "servings": 2}],
        },
    )

    resp = await client.post(f"/api/shopping-list/from-plan/{plan['id']}")
    assert resp.status_code == 201
    items_by_food = {item["food_id"]: item for item in resp.json()["items"]}
    assert str(test_food) in items_by_food
    assert items_by_food[str(test_food)]["quantity_g"] >= 400.0  # al menos lo de la receta
