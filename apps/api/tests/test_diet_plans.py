"""Tests del endpoint de planes de dieta (documento 2, "Motor de generación
de dietas"). La lógica matemática del solver ya está probada a fondo en
`test_diet_engine.py` — aquí se prueba el cableado: selección de
candidatos, filtrado de restricciones, persistencia y aislamiento (R3).

El fixture `diet_candidates` vive en `conftest.py` (compartido con los
tests de iafood, que también necesitan candidatos garantizados sin
depender de si el catálogo real está cargado — ver su docstring allí)."""


from sqlalchemy import text


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

    monkeypatch.setattr("myfood.routers.diet_plans.select_candidates", _fake_select_candidates)

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
