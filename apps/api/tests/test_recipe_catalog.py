"""Recetario compartido: recetas sin dueño que todo el mundo ve (migración 0022).

Lo que importa aquí es la frontera: una receta del catálogo se LEE, se copia y se usa en un
plan, pero no se edita ni se borra, y no se mezcla con las del usuario en ninguna de las dos
direcciones.
"""

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def clean_catalog(superuser_conn):
    """Una receta del catálogo no es de nadie, así que borrar el usuario de prueba no se la
    lleva: sin esto, las de un test se cuelan en el siguiente."""
    yield
    await superuser_conn.execute(text("DELETE FROM recipes WHERE user_id IS NULL"))
    await superuser_conn.commit()

async def _catalog_recipe(superuser_conn, test_food, name="Pollo al horno", **over):
    """Una receta del recetario compartido, como la dejaría el importador."""
    import uuid as _uuid

    recipe_id = _uuid.uuid4()
    await superuser_conn.execute(
        text(
            "INSERT INTO recipes (id, user_id, name, servings, instructions, source, "
            "source_id, cuisine, category, attribution) VALUES "
            "(:id, NULL, :name, :servings, 'Hornear.', 'themealdb', :sid, :cuisine, "
            ":category, 'TheMealDB')"
        ),
        {
            "id": str(recipe_id),
            "name": name,
            "servings": over.get("servings", 4),
            "sid": str(recipe_id)[:8],
            "cuisine": over.get("cuisine", "Spanish"),
            "category": over.get("category", "Chicken"),
        },
    )
    await superuser_conn.execute(
        text(
            "INSERT INTO recipe_ingredients (id, recipe_id, food_id, grams) "
            "VALUES (gen_random_uuid(), :rid, :fid, 400)"
        ),
        {"rid": str(recipe_id), "fid": str(test_food)},
    )
    await superuser_conn.commit()
    return recipe_id


async def test_the_catalog_is_visible_to_everyone_and_counts_per_serving(
    registered_client, superuser_conn, test_food
):
    """400 g de un alimento de 165 kcal/100 g entre 4 raciones: 165 kcal por ración."""
    client, _ = registered_client
    await _catalog_recipe(superuser_conn, test_food)

    body = (await client.get("/api/recipes/catalog")).json()
    mine = next(r for r in body["items"] if r["name"] == "Pollo al horno")
    assert mine["kcal_per_serving"] == 165.0
    assert mine["protein_g_per_serving"] == 31.0
    assert mine["ingredient_count"] == 1
    assert "Spanish" in body["cuisines"]
    assert "Chicken" in body["categories"]


async def test_the_catalog_does_not_mix_in_your_own_recipes(
    registered_client, superuser_conn, test_food
):
    client, _ = registered_client
    await client.post("/api/recipes", json={"name": "La mía", "servings": 1})
    await _catalog_recipe(superuser_conn, test_food)

    catalog = (await client.get("/api/recipes/catalog")).json()
    assert all(r["name"] != "La mía" for r in catalog["items"])
    # Y al revés: «mis recetas» no se llena con las 790 del catálogo.
    mine = (await client.get("/api/recipes")).json()
    assert [r["name"] for r in mine] == ["La mía"]


async def test_the_catalog_can_be_filtered(registered_client, superuser_conn, test_food):
    client, _ = registered_client
    await _catalog_recipe(superuser_conn, test_food, name="Paella valenciana", cuisine="Spanish")
    await _catalog_recipe(superuser_conn, test_food, name="Pad Thai", cuisine="Thai")

    por_texto = (await client.get("/api/recipes/catalog?q=paella")).json()
    assert [r["name"] for r in por_texto["items"]] == ["Paella valenciana"]

    por_cocina = (await client.get("/api/recipes/catalog?cuisine=Thai")).json()
    assert [r["name"] for r in por_cocina["items"]] == ["Pad Thai"]

    # 165 kcal por ración: un tope por debajo no deja pasar nada.
    por_kcal = (await client.get("/api/recipes/catalog?max_kcal=100")).json()
    assert por_kcal["items"] == []


async def test_a_catalog_recipe_can_be_read_but_not_edited(
    registered_client, superuser_conn, test_food
):
    client, _ = registered_client
    recipe_id = await _catalog_recipe(superuser_conn, test_food)

    detail = await client.get(f"/api/recipes/{recipe_id}")
    assert detail.status_code == 200
    assert detail.json()["name"] == "Pollo al horno"

    # No es tuya: no se toca.
    edited = await client.patch(f"/api/recipes/{recipe_id}", json={"name": "Mía"})
    assert edited.status_code == 404
    assert (await client.delete(f"/api/recipes/{recipe_id}")).status_code == 404


async def test_a_catalog_recipe_can_be_saved_as_mine(registered_client, superuser_conn, test_food):
    client, _ = registered_client
    recipe_id = await _catalog_recipe(superuser_conn, test_food)

    copied = await client.post(f"/api/recipes/{recipe_id}/copy")
    assert copied.status_code == 201
    assert copied.json()["name"] == "Pollo al horno"
    assert len(copied.json()["ingredients"]) == 1

    mine = (await client.get("/api/recipes")).json()
    assert [r["name"] for r in mine] == ["Pollo al horno"]
    # La copia es independiente: editarla no toca el catálogo.
    copy_id = copied.json()["id"]
    await client.patch(f"/api/recipes/{copy_id}", json={"name": "Mi pollo"})
    assert (await client.get(f"/api/recipes/{recipe_id}")).json()["name"] == "Pollo al horno"


async def test_copying_something_that_is_already_yours_is_refused(registered_client):
    client, _ = registered_client
    mine = (await client.post("/api/recipes", json={"name": "La mía", "servings": 1})).json()
    resp = await client.post(f"/api/recipes/{mine['id']}/copy")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "RECIPE_NOT_IN_CATALOG"
