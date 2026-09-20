"""Registro de recetas (`POST /log/recipe`), EAN interno con etiqueta y peso crudo o cocinado."""

import uuid
from datetime import date

import pytest
from sqlalchemy import text

from myfood.domain import ean

pytestmark = pytest.mark.asyncio

TODAY = date.today().isoformat()


async def _recipe(client, food_id, grams=200, servings=4, name="Pollo con algo"):
    resp = await client.post(
        "/api/recipes",
        json={
            "name": name,
            "servings": servings,
            "ingredients": [{"food_id": str(food_id), "grams": grams}],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- EAN interno y etiqueta ----------------------------------------------------------------------


async def test_a_new_recipe_gets_a_valid_internal_ean(registered_client, test_food):
    client, _ = registered_client
    recipe = await _recipe(client, test_food)
    assert ean.is_internal_ean(recipe["internal_ean"])


async def test_each_recipe_has_its_own_ean(registered_client, test_food):
    client, _ = registered_client
    first = await _recipe(client, test_food)
    second = await _recipe(client, test_food, name="Otra")
    assert first["internal_ean"] != second["internal_ean"]


async def test_a_recipe_without_ean_gets_one_when_opened(
    registered_client, test_food, superuser_conn
):
    client, _ = registered_client
    recipe = await _recipe(client, test_food)
    await superuser_conn.execute(
        text("UPDATE recipes SET internal_ean = NULL WHERE id = :id"), {"id": recipe["id"]}
    )
    await superuser_conn.commit()

    reopened = (await client.get(f"/api/recipes/{recipe['id']}")).json()

    assert ean.is_internal_ean(reopened["internal_ean"])
    assert (await client.get(f"/api/recipes/{recipe['id']}")).json()["internal_ean"] == reopened[
        "internal_ean"
    ]


async def test_the_printed_code_resolves_back_to_the_recipe(registered_client, test_food):
    client, _ = registered_client
    recipe = await _recipe(client, test_food)
    found = await client.get(f"/api/recipes/by-ean/{recipe['internal_ean']}")
    assert found.status_code == 200
    assert found.json()["id"] == recipe["id"]
    assert (await client.get("/api/recipes/by-ean/2000000000008")).status_code == 404


async def test_a_code_only_resolves_for_its_owner(registered_client, fresh_client, test_food):
    client, _ = registered_client
    other, _ = fresh_client
    recipe = await _recipe(client, test_food)
    assert (await other.get(f"/api/recipes/by-ean/{recipe['internal_ean']}")).status_code == 404


async def test_the_label_is_a_printable_svg_with_the_recipe_name(registered_client, test_food):
    client, _ = registered_client
    recipe = await _recipe(client, test_food, name="Lentejas de domingo")
    resp = await client.get(f"/api/recipes/{recipe['id']}/label.svg")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")
    assert "Lentejas de domingo" in resp.text
    assert "4 raciones" in resp.text


# --- registrar una receta ------------------------------------------------------------------------


async def test_logging_servings_of_a_recipe_snapshots_its_nutrition(registered_client, test_food):
    client, _ = registered_client
    recipe = await _recipe(client, test_food, grams=200, servings=4)  # 4 raciones de 50 g

    resp = await client.post(
        "/api/log/recipe",
        json={"log_date": TODAY, "meal_type": "dinner", "recipe_id": recipe["id"], "servings": 2},
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["recipe_id"] == recipe["id"]
    assert body["food_id"] is None
    assert body["recipe_name"] == "Pollo con algo"
    assert body["grams"] == 100.0  # 2 raciones x 50 g
    assert body["entry_source"] == "recipe"
    assert body["kcal"] == 165.0  # 200 g de pollo (330 kcal) / 4 raciones x 2
    assert body["protein_g"] == 31.0


async def test_the_day_log_names_recipe_entries_and_counts_them_in_the_totals(
    registered_client, test_food
):
    client, _ = registered_client
    recipe = await _recipe(client, test_food)
    await client.post(
        "/api/log/recipe",
        json={"log_date": TODAY, "meal_type": "lunch", "recipe_id": recipe["id"], "servings": 1},
    )

    day = (await client.get("/api/log", params={"date": TODAY})).json()

    assert day["food"][0]["recipe_name"] == "Pollo con algo"
    assert day["totals"]["kcal"] == 82.5


async def test_a_logged_recipe_does_not_change_when_the_recipe_is_edited(
    registered_client, test_food
):
    client, _ = registered_client
    recipe = await _recipe(client, test_food, grams=200, servings=1)
    await client.post(
        "/api/log/recipe",
        json={"log_date": TODAY, "meal_type": "lunch", "recipe_id": recipe["id"], "servings": 1},
    )
    ingredient = recipe["ingredients"][0]
    await client.patch(
        f"/api/recipes/{recipe['id']}/ingredients/{ingredient['id']}",
        json={"food_id": str(test_food), "grams": 400},
    )

    day = (await client.get("/api/log", params={"date": TODAY})).json()

    assert day["food"][0]["kcal"] == 330.0  # el snapshot sigue siendo el de 200 g


async def test_logging_a_recipe_validates_servings_and_ownership(
    registered_client, fresh_client, test_food
):
    client, _ = registered_client
    other, _ = fresh_client
    recipe = await _recipe(client, test_food)
    body = {"log_date": TODAY, "meal_type": "lunch", "recipe_id": recipe["id"]}

    assert (await client.post("/api/log/recipe", json={**body, "servings": 0})).status_code == 422
    assert (await client.post("/api/log/recipe", json={**body, "servings": 21})).status_code == 422
    assert (
        await client.post(
            "/api/log/recipe", json={**body, "recipe_id": str(uuid.uuid4()), "servings": 1}
        )
    ).status_code == 404
    assert (await other.post("/api/log/recipe", json={**body, "servings": 1})).status_code == 404


async def test_a_recipe_without_ingredients_cannot_be_logged(registered_client):
    client, _ = registered_client
    empty = (await client.post("/api/recipes", json={"name": "Vacía", "servings": 1})).json()
    resp = await client.post(
        "/api/log/recipe",
        json={"log_date": TODAY, "meal_type": "lunch", "recipe_id": empty["id"], "servings": 1},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "RECIPE_HAS_NO_INGREDIENTS"


async def test_logging_a_recipe_twice_with_the_same_client_id_does_not_duplicate(
    registered_client, test_food
):
    client, _ = registered_client
    recipe = await _recipe(client, test_food)
    payload = {
        "log_date": TODAY,
        "meal_type": "lunch",
        "recipe_id": recipe["id"],
        "servings": 1,
        "client_id": str(uuid.uuid4()),
    }
    first = await client.post("/api/log/recipe", json=payload)
    second = await client.post("/api/log/recipe", json=payload)
    assert first.json()["id"] == second.json()["id"]
    assert len((await client.get("/api/log", params={"date": TODAY})).json()["food"]) == 1


# --- peso crudo o cocinado -----------------------------------------------------------------------


@pytest.fixture
async def rice(test_food, superuser_conn):
    """El alimento de prueba con un factor de cocción de 2,5 (250 g cocido = 100 g crudo)."""
    await superuser_conn.execute(
        text("UPDATE foods SET cooking_yield_factor = 2.5 WHERE id = :id"), {"id": str(test_food)}
    )
    await superuser_conn.commit()
    return test_food


async def test_a_cooked_weight_is_stored_as_the_raw_equivalent(registered_client, rice):
    client, _ = registered_client
    resp = await client.post(
        "/api/log/food",
        json={
            "log_date": TODAY,
            "meal_type": "lunch",
            "food_id": str(rice),
            "grams": 250,
            "weighed_as": "cooked",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["grams"] == 100.0
    assert body["entered_grams"] == 250.0
    assert body["weighed_as"] == "cooked"
    assert body["kcal"] == 165.0  # 100 g crudos x 165 kcal/100 g, no 250 g


async def test_a_raw_weight_is_left_as_is(registered_client, rice):
    client, _ = registered_client
    body = (
        await client.post(
            "/api/log/food",
            json={"log_date": TODAY, "meal_type": "lunch", "food_id": str(rice), "grams": 100},
        )
    ).json()
    assert body["grams"] == 100.0
    assert body["weighed_as"] == "raw"
    assert body["entered_grams"] is None


async def test_cooked_needs_a_cooking_yield_factor(registered_client, test_food):
    client, _ = registered_client
    resp = await client.post(
        "/api/log/food",
        json={
            "log_date": TODAY,
            "meal_type": "lunch",
            "food_id": str(test_food),
            "grams": 250,
            "weighed_as": "cooked",
        },
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "NO_COOKING_YIELD"


async def test_editing_a_cooked_entry_keeps_interpreting_grams_as_cooked(registered_client, rice):
    client, _ = registered_client
    entry = (
        await client.post(
            "/api/log/food",
            json={
                "log_date": TODAY,
                "meal_type": "lunch",
                "food_id": str(rice),
                "grams": 250,
                "weighed_as": "cooked",
            },
        )
    ).json()

    edited = (await client.patch(f"/api/log/food/{entry['id']}", json={"grams": 500})).json()

    assert edited["grams"] == 200.0
    assert edited["entered_grams"] == 500.0
    assert edited["kcal"] == 330.0


async def test_the_food_detail_exposes_the_cooking_yield(registered_client, rice, test_food):
    client, _ = registered_client
    assert (await client.get(f"/api/foods/{test_food}")).json()["cooking_yield_factor"] == 2.5
