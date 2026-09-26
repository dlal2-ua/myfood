"""Comidas guardadas (migración 0024).

Lo que hay que atar: que se guarde el snapshot y no una referencia al catálogo, que repetir
apunte exactamente lo mismo, que los platos estimados sin `food_id` sobrevivan, y que nadie vea
ni repita las comidas de otro.
"""

import uuid

import pytest
from sqlalchemy import text

from myfood.db.session import AdminSessionLocal

pytestmark = pytest.mark.asyncio


async def _seed_food(conn, name="Pan de prueba", kcal=250.0, protein=8.0):
    food_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO foods (id, kind, source, source_id, license, name_es, quality_rank) "
            "VALUES (:id, 'generic', 'test', :sid, 'CC0', :name, 1)"
        ),
        {"id": str(food_id), "sid": str(food_id), "name": name},
    )
    await conn.execute(
        text(
            "INSERT INTO food_nutrients (food_id, kcal_100g, protein_100g, fat_100g, "
            "carbs_100g, micros) VALUES (:id, :kcal, :protein, 2, 48, '{}'::jsonb)"
        ),
        {"id": str(food_id), "kcal": kcal, "protein": protein},
    )
    await conn.commit()
    return str(food_id)


async def _borrar_alimentos(conn, *food_ids):
    """El alimento no se puede borrar mientras lo referencien el diario o una comida guardada."""
    ids = [str(f) for f in food_ids]
    await conn.execute(
        text("DELETE FROM saved_meal_items WHERE food_id = ANY(:ids)"), {"ids": ids}
    )
    await conn.execute(text("DELETE FROM food_log WHERE food_id = ANY(:ids)"), {"ids": ids})
    await conn.execute(text("DELETE FROM foods WHERE id = ANY(:ids)"), {"ids": ids})
    await conn.commit()


async def _log(client, food_id, *, day, meal="breakfast", grams=100):
    resp = await client.post(
        "/api/log/food",
        json={"log_date": day, "meal_type": meal, "food_id": food_id, "grams": grams},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- guardar ---------------------------------------------------------------------------------


async def test_guardar_una_comida_copia_el_snapshot_y_no_una_referencia(
    registered_client, superuser_conn
):
    """Repetir una comida guardada dentro de un año tiene que apuntar lo mismo aunque el
    catálogo haya cambiado de por medio: se copia lo que el usuario comió y confirmó."""
    client, _ = registered_client
    food_id = await _seed_food(superuser_conn)
    try:
        await _log(client, food_id, day="2026-09-20", grams=200)

        resp = await client.post(
            "/api/saved-meals",
            json={"name": "Mi desayuno", "log_date": "2026-09-20", "meal_type": "breakfast"},
        )
        assert resp.status_code == 201, resp.text
        saved = resp.json()
        assert saved["name"] == "Mi desayuno"
        assert saved["totals"]["kcal"] == 500.0  # 250 kcal/100 g × 200 g
        assert [i["grams"] for i in saved["items"]] == [200.0]

        # El catálogo cambia después: la comida guardada no se entera, a propósito.
        await superuser_conn.execute(
            text("UPDATE food_nutrients SET kcal_100g = 999 WHERE food_id = :id"),
            {"id": food_id},
        )
        await superuser_conn.commit()
        listado = (await client.get("/api/saved-meals")).json()["items"]
        assert listado[0]["totals"]["kcal"] == 500.0
    finally:
        await _borrar_alimentos(superuser_conn, food_id)


async def test_guardar_una_comida_vacia_no_crea_nada(registered_client):
    client, _ = registered_client
    resp = await client.post(
        "/api/saved-meals",
        json={"name": "Nada", "log_date": "2026-09-01", "meal_type": "dinner"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "EMPTY_MEAL"


async def test_guardar_con_un_nombre_que_ya_existe_lo_reemplaza(
    registered_client, superuser_conn
):
    """Dos «Mi desayuno» solo confunden."""
    client, _ = registered_client
    food_id = await _seed_food(superuser_conn)
    try:
        await _log(client, food_id, day="2026-09-20", grams=100)
        await client.post(
            "/api/saved-meals",
            json={"name": "Mi desayuno", "log_date": "2026-09-20", "meal_type": "breakfast"},
        )
        await _log(client, food_id, day="2026-09-21", grams=300)
        resp = await client.post(
            "/api/saved-meals",
            json={"name": "mi DESAYUNO", "log_date": "2026-09-21", "meal_type": "breakfast"},
        )
        assert resp.status_code == 201

        listado = (await client.get("/api/saved-meals")).json()["items"]
        assert len(listado) == 1
        assert [i["grams"] for i in listado[0]["items"]] == [300.0]
    finally:
        await _borrar_alimentos(superuser_conn, food_id)


# --- repetir ---------------------------------------------------------------------------------


async def test_repetir_apunta_la_comida_entera_y_cuenta_el_uso(registered_client, superuser_conn):
    client, _ = registered_client
    pan = await _seed_food(superuser_conn, "Pan de prueba")
    queso = await _seed_food(superuser_conn, "Queso de prueba", kcal=350.0, protein=25.0)
    try:
        await _log(client, pan, day="2026-09-20", grams=60)
        await _log(client, queso, day="2026-09-20", grams=30)
        meal_id = (
            await client.post(
                "/api/saved-meals",
                json={"name": "Tostada", "log_date": "2026-09-20", "meal_type": "breakfast"},
            )
        ).json()["id"]

        resp = await client.post(
            f"/api/saved-meals/{meal_id}/log",
            json={"log_date": "2026-09-25", "meal_type": "afternoon_snack"},
        )
        assert resp.status_code == 201
        assert resp.json() == {"logged": 2}

        dia = (await client.get("/api/log?date=2026-09-25")).json()
        assert len(dia["food"]) == 2
        assert {e["meal_type"] for e in dia["food"]} == {"afternoon_snack"}
        # `saved_meal` y no `manual`: en el histórico se distingue lo repetido de lo buscado.
        assert {e["entry_source"] for e in dia["food"]} == {"saved_meal"}
        assert dia["totals"]["kcal"] == 255.0  # 60 g de pan (150) + 30 g de queso (105)

        # Lo que más se repite manda el orden de la lista.
        assert (await client.get("/api/saved-meals")).json()["items"][0]["use_count"] == 1
    finally:
        await _borrar_alimentos(superuser_conn, pan, queso)


async def test_un_plato_estimado_sin_alimento_del_catalogo_sobrevive_al_guardarse(
    registered_client, superuser_conn
):
    """«Bocadillo de sobrasada» no existe en `foods`; guardarlo es justo para lo que sirve
    esto. La línea va con `custom_name` y sin `food_id`, como en la migración 0020."""
    client, user_id = registered_client
    async with AdminSessionLocal() as session:
        await session.execute(
            text(
                "INSERT INTO food_log (user_id, log_date, meal_type, custom_name, grams, "
                "entry_source, kcal, protein_g, fat_g, carbs_g, micros) VALUES "
                "(:u, '2026-09-20', 'lunch', 'Bocadillo de sobrasada', 200, 'ai_estimate', "
                "520, 18, 26, 52, '{}'::jsonb)"
            ),
            {"u": str(user_id)},
        )
        await session.commit()

    saved = (
        await client.post(
            "/api/saved-meals",
            json={"name": "Bocata de siempre", "log_date": "2026-09-20", "meal_type": "lunch"},
        )
    ).json()
    assert saved["items"][0]["name"] == "Bocadillo de sobrasada"
    assert saved["items"][0]["food_id"] is None
    assert saved["items"][0]["estimated"] is True
    assert saved["totals"]["kcal"] == 520.0

    await client.post(
        f"/api/saved-meals/{saved['id']}/log",
        json={"log_date": "2026-09-26", "meal_type": "dinner"},
    )
    dia = (await client.get("/api/log?date=2026-09-26")).json()
    assert dia["food"][0]["food_name"] == "Bocadillo de sobrasada"
    assert dia["totals"]["kcal"] == 520.0


# --- aislamiento -------------------------------------------------------------------------------


async def test_no_se_ve_ni_se_repite_la_comida_guardada_de_otro(
    registered_client, two_users, superuser_conn
):
    client, _ = registered_client
    otro_id, _ = two_users
    meal_id = uuid.uuid4()
    async with AdminSessionLocal() as session:
        await session.execute(
            text("INSERT INTO saved_meals (id, user_id, name) VALUES (:i, :u, 'Lo suyo')"),
            {"i": str(meal_id), "u": str(otro_id)},
        )
        await session.commit()

    assert (await client.get("/api/saved-meals")).json()["items"] == []
    resp = await client.post(
        f"/api/saved-meals/{meal_id}/log",
        json={"log_date": "2026-09-26", "meal_type": "lunch"},
    )
    assert resp.status_code == 404
    assert (await client.delete(f"/api/saved-meals/{meal_id}")).status_code == 404
