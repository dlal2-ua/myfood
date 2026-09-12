"""GET /foods/{food_id}/similar (sección "Alimentos similares
(sustituciones)") — usa alimentos reales insertados a mano en la BD
compartida (mismo patrón que el fixture `test_food` de conftest.py), no
mocks ni una BD aparte.
"""

import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio


async def _insert_food(conn, name_es, kcal, protein, fat, carbs, fiber, salt, vec=None):
    food_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO foods (id, kind, source, source_id, license, name_es, quality_rank) "
            "VALUES (:id, 'generic', 'test', :sid, 'CC0', :name, 1)"
        ),
        {"id": str(food_id), "sid": str(food_id), "name": name_es},
    )
    await conn.execute(
        text(
            "INSERT INTO food_nutrients "
            "(food_id, kcal_100g, protein_100g, fat_100g, carbs_100g, fiber_100g, salt_100g) "
            "VALUES (:id, :kcal, :protein, :fat, :carbs, :fiber, :salt)"
        ),
        {
            "id": str(food_id),
            "kcal": kcal,
            "protein": protein,
            "fat": fat,
            "carbs": carbs,
            "fiber": fiber,
            "salt": salt,
        },
    )
    if vec is not None:
        vec_str = "[" + ",".join(str(v) for v in vec) + "]"
        # Literal interpolado, no bind param — misma razón que en
        # scripts/build_food_vectors.py (asyncpg no trae códec para el tipo
        # `vector` sin el paquete opcional pgvector-python); son floats de
        # este propio test, nunca texto de usuario.
        await conn.execute(
            text(f"INSERT INTO food_vectors (food_id, vec) VALUES (:id, '{vec_str}'::vector)"),
            {"id": str(food_id)},
        )
    return food_id


@pytest.fixture
async def similarity_catalog(superuser_conn):
    # `food_vectors` ya tiene ~21.801 filas reales (el catálogo completo) para
    # cuando corren estos tests, así que un perfil "realista" (p. ej. pollo:
    # ~165kcal/31g proteína) tendría decenas de vecinos reales casi idénticos
    # y el orden esperado entre los alimentos de este fixture dejaría de ser
    # determinista. Para aislar el test del contenido del catálogo real, se
    # usa una combinación de macros físicamente imposible en un alimento real
    # (proteína Y grasa simultáneamente por encima de 80g/100g — ninguna fila
    # real cumple protein_100g > 80 AND fat_100g > 80, comprobado contra la
    # BD compartida) para garantizar que los vecinos más cercanos de `base`
    # solo puedan ser los propios alimentos sintéticos de este fixture.
    #
    # Vectores elegidos para que la distancia L2 a `base` quede en un orden
    # claro e inequívoco: closest << allergenic << banned << farthest.
    base = await _insert_food(
        superuser_conn, "Base sintética", 500, 90, 90, 0, 80, 80,
        [0.555556, 0.9, 0.9, 0, 0.8, 0.8],
    )
    closest = await _insert_food(
        superuser_conn, "Cercano sintético", 505, 90, 90, 0, 80, 80,
        [0.561111, 0.9, 0.9, 0, 0.8, 0.8],
    )
    farthest = await _insert_food(
        superuser_conn, "Lejano sintético", 0, 0, 0, 0, 0, 0,
        [0.0, 0.0, 0.0, 0, 0.0, 0.0],
    )
    allergenic = await _insert_food(
        superuser_conn, "Gamba sintética con alérgeno", 600, 85, 85, 0, 75, 75,
        [0.666667, 0.85, 0.85, 0, 0.75, 0.75],
    )
    banned = await _insert_food(
        superuser_conn, "Prohibido sintético por el usuario", 700, 80, 80, 0, 70, 70,
        [0.777778, 0.8, 0.8, 0, 0.7, 0.7],
    )
    no_vector = await _insert_food(superuser_conn, "Sin vector todavía", 500, 90, 90, 0, 80, 80)

    await superuser_conn.execute(
        text("INSERT INTO food_allergens (food_id, allergen_code) VALUES (:id, 'crustaceos')"),
        {"id": str(allergenic)},
    )
    await superuser_conn.commit()

    ids = {
        "base": base,
        "closest": closest,
        "farthest": farthest,
        "allergenic": allergenic,
        "banned": banned,
        "no_vector": no_vector,
    }
    yield ids

    for food_id in ids.values():
        await superuser_conn.execute(
            text("DELETE FROM food_allergens WHERE food_id = :id"), {"id": str(food_id)}
        )
        await superuser_conn.execute(
            text("DELETE FROM food_vectors WHERE food_id = :id"), {"id": str(food_id)}
        )
        await superuser_conn.execute(
            text("DELETE FROM food_nutrients WHERE food_id = :id"), {"id": str(food_id)}
        )
        await superuser_conn.execute(text("DELETE FROM foods WHERE id = :id"), {"id": str(food_id)})
    await superuser_conn.commit()


async def test_similar_excludes_allergen_and_banned_foods(registered_client, similarity_catalog):
    client, _ = registered_client
    ids = similarity_catalog

    restricted = await client.post(
        "/api/restrictions", json={"kind": "allergen", "allergen_code": "crustaceos"}
    )
    assert restricted.status_code == 201
    banned = await client.post(
        "/api/restrictions", json={"kind": "banned_food", "food_id": str(ids["banned"])}
    )
    assert banned.status_code == 201

    resp = await client.get(f"/api/foods/{ids['base']}/similar", params={"limit": 3})
    assert resp.status_code == 200
    items = resp.json()["items"]
    returned_ids = [item["id"] for item in items]

    assert str(ids["allergenic"]) not in returned_ids
    assert str(ids["banned"]) not in returned_ids
    assert str(ids["base"]) not in returned_ids

    # El más parecido nutricionalmente debe ir primero.
    assert returned_ids[0] == str(ids["closest"])
    distances = [item["distance"] for item in items]
    assert distances == sorted(distances)


async def test_similar_without_restrictions_includes_allergenic_food(
    registered_client, similarity_catalog
):
    """Sin restricciones registradas, el alimento con alérgeno SÍ debe poder
    aparecer — confirma que el filtro depende de las restricciones del
    usuario y no excluye alérgenos de forma incondicional."""
    client, _ = registered_client
    ids = similarity_catalog

    resp = await client.get(f"/api/foods/{ids['base']}/similar", params={"limit": 10})
    assert resp.status_code == 200
    returned_ids = {item["id"] for item in resp.json()["items"]}
    assert str(ids["allergenic"]) in returned_ids


async def test_similar_returns_response_shape(registered_client, similarity_catalog):
    client, _ = registered_client
    ids = similarity_catalog

    resp = await client.get(f"/api/foods/{ids['base']}/similar", params={"limit": 1})
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["id"] == str(ids["closest"])
    assert item["name_es"] == "Cercano sintético"
    assert item["kcal_100g"] == 505.0
    assert isinstance(item["distance"], float)


async def test_similar_unknown_food_is_404(registered_client):
    client, _ = registered_client
    resp = await client.get(f"/api/foods/{uuid.uuid4()}/similar")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "FOOD_NOT_FOUND"


async def test_similar_food_without_vector_is_404(registered_client, similarity_catalog):
    client, _ = registered_client
    resp = await client.get(f"/api/foods/{similarity_catalog['no_vector']}/similar")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "FOOD_VECTOR_NOT_FOUND"
