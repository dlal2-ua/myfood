"""Tests del endpoint de planes de dieta (documento 2, "Motor de generación
de dietas"). La lógica matemática del solver ya está probada a fondo en
`test_diet_engine.py` — aquí se prueba el cableado: selección de
candidatos, filtrado de restricciones, persistencia y aislamiento (R3)."""

import uuid

import pytest_asyncio
from sqlalchemy import text


@pytest_asyncio.fixture
async def diet_candidates(superuser_conn):
    """Un puñado de alimentos reales y nutricionalmente diversos (proteína,
    carbohidrato, grasa, verdura) — sin esto el candidate pool real (que
    excluye 'user'/'recipe' y filtra por macros) podría no tener suficiente
    variedad en una BD de test, dejando el plan infactible por falta de
    materia prima, no por un fallo real.

    La selección de candidatos del router pilla los N mejores de cada
    macronutriente (`ORDER BY protein_100g DESC LIMIT 40`, etc.) sobre TODA
    `foods` — en este entorno esa tabla ya tiene el catálogo real completo
    (miles de alimentos de USDA/CIQUAL/BEDCA/OFF), así que un valor "normal"
    de macros no garantiza en absoluto que estos alimentos de prueba entren
    en el candidate pool, y el router también exige `kcal_100g` en un rango
    "realista" (20-600, ver `_MIN/MAX_REALISTIC_KCAL_100G`) para dejar fuera
    aceites puros y productos casi sin calorías.

    Los dos primeros usan un valor justo por encima de 100 g/100 g en
    proteína/carbohidrato — imposible para cualquier alimento real (las
    reglas de descarte del ETL exigen proteína+grasa+carbohidratos ≤100 g,
    sección 11.2) pero con `kcal_100g` calculado de forma coherente con esa
    macro (4 kcal/g) para quedar dentro del rango realista — garantizados en
    la cabeza de su bucket sin depender de qué haya en el catálogo real, y
    sin desbordar el objetivo del día ni siquiera con la cantidad mínima del
    solver (20 g). El mismo truco no es posible para grasa (9 kcal/g × 100 g
    ya son 900 kcal, siempre por encima del rango realista) — para ese
    bucket se usa un valor alto pero no "imposible" (60 g/100 g), razonable
    porque los alimentos con más grasa dentro del rango realista (aceites
    puros excluidos) rara vez lo superan.

    Se detectó en la práctica, en este orden: (1) un valor de macro
    "imposible" pero con kcal declarado bajo e inconsistente (400 kcal con
    900 g de proteína) le da al solver un "chollo" que no existe en ningún
    alimento real; (2) corregido eso, un valor todavía demasiado alto
    (900 g/100 g) desborda el objetivo del día incluso en la cantidad
    mínima (20 g) por sí solo; (3) ya con 101 g/100 g SÍ funcionaba para
    proteína/carbohidrato, pero reveló que el propio candidate pool real
    (antes de este fixture) arrastraba salvado de maíz, algas deshidratadas
    y aceites/mantecas puras por su densidad de macro — de ahí el filtro de
    `kcal_100g` en rango realista y la eliminación del cubo de fibra en
    `routers/diet_plans.py` (la fibra no es un objetivo del solver).

    También hay un filtro de "ningún macro por sí solo pasa del 90% de las
    kcal" (mismo módulo) — un alimento sintético de un solo macro puro
    (p. ej. proteína=101, todo lo demás 0) lo incumple de sobra (100% de
    sus kcal vienen de ese único macro). Se añade un segundo macro
    secundario modesto a cada uno para quedar por debajo del 90% sin dejar
    de superar los 100 g/100 g "imposibles" en el macro dominante."""
    foods = [
        ("Súper-proteína (test)", round((101 + 20) * 4), 101, 0, 20),
        ("Súper-carbohidrato (test)", round((101 + 20) * 4), 20, 0, 101),
        ("Alto en grasa (test)", round(50 * 9 + 15 * 4 + 5 * 4), 15, 50, 5),
        ("Verdura de prueba (test)", 40, 3, 0.4, 7),
        ("Huevo (test)", 155, 13, 11, 1.1),
        ("Lentejas cocidas (test)", 116, 9, 0.4, 20),
    ]
    ids = []
    for name, kcal, protein, fat, carbs in foods:
        food_id = uuid.uuid4()
        ids.append(food_id)
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
                "(food_id, kcal_100g, protein_100g, fat_100g, carbs_100g) "
                "VALUES (:id, :kcal, :protein, :fat, :carbs)"
            ),
            {
                "id": str(food_id),
                "kcal": kcal,
                "protein": protein,
                "fat": fat,
                "carbs": carbs,
            },
        )
    await superuser_conn.commit()
    yield ids
    for food_id in ids:
        await superuser_conn.execute(
            text("DELETE FROM plan_items WHERE food_id = :id"), {"id": str(food_id)}
        )
        await superuser_conn.execute(
            text("DELETE FROM plan_item_alternatives WHERE food_id = :id"), {"id": str(food_id)}
        )
        await superuser_conn.execute(
            text("DELETE FROM food_vectors WHERE food_id = :id"), {"id": str(food_id)}
        )
    await superuser_conn.execute(
        text("DELETE FROM foods WHERE id = ANY(:ids)"), {"ids": [str(i) for i in ids]}
    )
    await superuser_conn.commit()


async def _complete_profile(client):
    await client.put(
        "/api/profile",
        json={"sex": "male", "birth_date": "1995-01-01", "height_cm": 180, "meals_per_day": 3},
    )
    await client.post("/api/measurements", json={"measured_on": "2026-01-10", "weight_kg": 80})


async def test_generate_plan_requires_complete_profile(registered_client):
    client, _user_id = registered_client
    resp = await client.post("/api/diet-plans/generate", json={"num_days": 1})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "PROFILE_INCOMPLETE"


async def test_generate_plan_requires_measurement(registered_client):
    client, _user_id = registered_client
    await client.put(
        "/api/profile", json={"sex": "male", "birth_date": "1995-01-01", "height_cm": 180}
    )
    resp = await client.post("/api/diet-plans/generate", json={"num_days": 1})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "MISSING_MEASUREMENTS"


async def test_generate_plan_golden_path(registered_client, diet_candidates):
    client, _user_id = registered_client
    await _complete_profile(client)

    resp = await client.post(
        "/api/diet-plans/generate", json={"name": "Plan de prueba", "num_days": 2}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Plan de prueba"
    assert len(body["days"]) == 2
    for day in body["days"]:
        assert len(day["meals"]) == 3  # meals_per_day=3 -> breakfast/lunch/dinner
        assert {m["meal_type"] for m in day["meals"]} == {"breakfast", "lunch", "dinner"}
        for meal in day["meals"]:
            assert len(meal["items"]) >= 1
            for item in meal["items"]:
                assert item["grams"] > 0


async def test_generated_plan_totals_are_reasonably_close_to_targets(
    registered_client, diet_candidates
):
    client, _user_id = registered_client
    await _complete_profile(client)
    targets = (await client.get("/api/calc/targets")).json()

    resp = await client.post("/api/diet-plans/generate", json={"num_days": 1})
    day = resp.json()["days"][0]
    assert abs(day["totals"]["kcal"] - targets["kcal"]) <= targets["kcal"] * 0.2


async def test_restricted_food_never_appears_in_generated_plan(
    registered_client, diet_candidates, superuser_conn
):
    client, user_id = registered_client
    await _complete_profile(client)
    banned_food_id = diet_candidates[0]  # "Súper-proteína", garantizado en el candidate pool

    await superuser_conn.execute(
        text(
            "INSERT INTO user_restrictions (id, user_id, kind, food_id) "
            "VALUES (gen_random_uuid(), :uid, 'banned_food', :food_id)"
        ),
        {"uid": str(user_id), "food_id": str(banned_food_id)},
    )
    await superuser_conn.commit()

    resp = await client.post("/api/diet-plans/generate", json={"num_days": 2})
    assert resp.status_code == 201
    used_food_ids = {
        item["food_id"]
        for day in resp.json()["days"]
        for meal in day["meals"]
        for item in meal["items"]
    }
    assert str(banned_food_id) not in used_food_ids


async def test_list_get_patch_delete_plan(registered_client, diet_candidates):
    client, _user_id = registered_client
    await _complete_profile(client)
    created = await client.post("/api/diet-plans/generate", json={"num_days": 1})
    plan_id = created.json()["id"]

    listed = await client.get("/api/diet-plans")
    assert any(p["id"] == plan_id for p in listed.json())

    detail = await client.get(f"/api/diet-plans/{plan_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == plan_id

    patched = await client.patch(f"/api/diet-plans/{plan_id}", json={"status": "active"})
    assert patched.status_code == 200
    assert patched.json()["status"] == "active"

    deleted = await client.delete(f"/api/diet-plans/{plan_id}")
    assert deleted.status_code == 204
    after = await client.get(f"/api/diet-plans/{plan_id}")
    assert after.status_code == 404


async def test_cross_user_isolation(registered_client, diet_candidates, two_users, superuser_conn):
    client, _own_user_id = registered_client
    user_a, _user_b = two_users

    other_plan_id = (
        await superuser_conn.execute(
            text(
                "INSERT INTO diet_plans "
                "(id, user_id, name, start_date, target_kcal, target_protein_g, "
                "target_fat_g, target_carbs_g) "
                "VALUES (gen_random_uuid(), :uid, 'Ajeno', CURRENT_DATE, 2000, 150, 60, 200) "
                "RETURNING id"
            ),
            {"uid": str(user_a)},
        )
    ).scalar_one()
    await superuser_conn.commit()

    assert (await client.get(f"/api/diet-plans/{other_plan_id}")).status_code == 404
    assert (
        await client.patch(f"/api/diet-plans/{other_plan_id}", json={"status": "active"})
    ).status_code == 404
    assert (await client.delete(f"/api/diet-plans/{other_plan_id}")).status_code == 404

    await superuser_conn.execute(
        text("DELETE FROM diet_plans WHERE id = :id"), {"id": str(other_plan_id)}
    )
    await superuser_conn.commit()


async def test_substitute_item_updates_food_and_recomputes_alternatives(
    registered_client, diet_candidates, superuser_conn, monkeypatch
):
    client, _user_id = registered_client
    await _complete_profile(client)

    # Vectores sintéticos para que haya alguna alternativa que ofrecer —
    # sin esto `food_vectors` está vacía en el entorno de test y no habría
    # nada que sustituir (comportamiento correcto pero no probaría el flujo).
    for i, food_id in enumerate(diet_candidates):
        vec = [float(i), 0.0, 0.0, 0.0, 0.0, 0.0]
        await superuser_conn.execute(
            text("INSERT INTO food_vectors (food_id, vec) VALUES (:id, CAST(:vec AS vector))"),
            {"id": str(food_id), "vec": str(vec)},
        )
    await superuser_conn.commit()

    # El pool de candidatos real mezcla estos 6 alimentos de prueba con todo
    # el catálogo real (miles de alimentos) — el solver podría, con razón,
    # preferir alimentos reales bien ajustados a los objetivos y no usar
    # ninguno de los que aquí tienen vector. Para probar la sustitución de
    # forma determinista (no probabilística) se sustituye la selección de
    # candidatos para que sean *solo* estos 6 — el resto del flujo (solver,
    # persistencia, cálculo de alternativas, endpoint de sustitución) sigue
    # siendo el real, sin mockear.
    from myfood.domain.diet_engine import CandidateFood

    fixed_candidates = [
        CandidateFood(
            id=str(food_id),
            name_es=f"food-{i}",
            kcal_100g=200,
            protein_100g=15,
            fat_100g=8,
            carbs_100g=20,
        )
        for i, food_id in enumerate(diet_candidates)
    ]

    async def _fake_select_candidates(session, user_id):
        return fixed_candidates

    monkeypatch.setattr("myfood.routers.diet_plans._select_candidates", _fake_select_candidates)

    created = await client.post("/api/diet-plans/generate", json={"num_days": 1})
    plan = created.json()
    items_with_alternatives = [
        item
        for day in plan["days"]
        for meal in day["meals"]
        for item in meal["items"]
        if item["alternatives"]
    ]
    assert items_with_alternatives, (
        "ningún alimento del plan generado tenía alternativas — no debería "
        "pasar con los 6 vectores sintéticos ya insertados para todos los "
        "candidatos garantizados del fixture"
    )
    item = items_with_alternatives[0]
    alternative = item["alternatives"][0]

    resp = await client.post(
        f"/api/diet-plans/{plan['id']}/items/{item['id']}/substitute",
        json={"alternative_id": alternative["id"]},
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["food_id"] == alternative["food_id"]
    assert updated["grams"] == alternative["grams"]
