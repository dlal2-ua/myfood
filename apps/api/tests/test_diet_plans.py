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
    registered_client, diet_candidates, superuser_conn
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
        "pasar con los vectores sintéticos ya insertados para todos los "
        "candidatos del fixture"
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


# --- Fase 4: calidad del plan, un solo plan activo y edición de elementos ----------------------

import time  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402


async def test_each_day_reports_its_warning_and_whether_the_solver_finished(
    registered_client, diet_candidates
):
    client, _user_id = registered_client
    await _complete_profile(client)

    plan = (await client.post("/api/diet-plans/generate", json={"num_days": 2})).json()

    for day in plan["days"]:
        assert day["warning"] in (None, "TARGETS_NOT_MET")
        assert isinstance(day["is_optimal"], bool)


async def test_a_generated_week_meets_the_acceptance_criteria(registered_client, diet_candidates):
    """Fase 4: 7 días con desviación ≤ 5 % en kcal y ≥ 90 % de la proteína objetivo, en menos de
    60 s, y con la estructura de comidas de cada tipo."""
    client, _user_id = registered_client
    await _complete_profile(client)
    targets = (await client.get("/api/calc/targets")).json()

    started = time.monotonic()
    resp = await client.post("/api/diet-plans/generate", json={"num_days": 7})
    elapsed = time.monotonic() - started

    assert resp.status_code == 201
    assert elapsed < 60
    days = resp.json()["days"]
    assert len(days) == 7
    for day in days:
        assert abs(day["totals"]["kcal"] - targets["kcal"]) <= targets["kcal"] * 0.05
        assert day["totals"]["protein_g"] >= targets["protein_g"] * 0.9
        assert day["warning"] is None
        for meal in day["meals"]:
            for item in meal["items"]:
                assert item["grams"] % 5 == 0


async def test_activating_a_plan_archives_the_one_that_was_active(
    registered_client, diet_candidates
):
    client, _user_id = registered_client
    await _complete_profile(client)
    first = (await client.post("/api/diet-plans/generate", json={"num_days": 1})).json()
    second = (await client.post("/api/diet-plans/generate", json={"num_days": 1})).json()

    assert (
        await client.patch(f"/api/diet-plans/{first['id']}", json={"status": "active"})
    ).status_code == 200
    assert (
        await client.patch(f"/api/diet-plans/{second['id']}", json={"status": "active"})
    ).status_code == 200

    statuses = {p["id"]: p["status"] for p in (await client.get("/api/diet-plans")).json()}
    assert statuses[second["id"]] == "active"
    assert statuses[first["id"]] == "archived"


async def test_the_database_allows_a_single_active_plan_per_user(
    registered_client, superuser_conn
):
    _client, user_id = registered_client
    insert = text(
        "INSERT INTO diet_plans (user_id, name, start_date, status, target_kcal, "
        "target_protein_g, target_fat_g, target_carbs_g) "
        "VALUES (:u, 'p', '2026-01-01', 'active', 2000, 100, 60, 200)"
    )
    await superuser_conn.execute(insert, {"u": str(user_id)})
    with pytest.raises(IntegrityError):
        await superuser_conn.execute(insert, {"u": str(user_id)})
    await superuser_conn.rollback()


async def _first_item(client):
    await _complete_profile(client)
    plan = (await client.post("/api/diet-plans/generate", json={"num_days": 1})).json()
    item = next(i for d in plan["days"] for m in d["meals"] for i in m["items"])
    return plan, item


async def test_an_item_can_be_edited_by_hand(registered_client, diet_candidates, superuser_conn):
    client, _user_id = registered_client
    plan, item = await _first_item(client)

    resp = await client.put(
        f"/api/diet-plans/{plan['id']}/items/{item['id']}", json={"grams": 135}
    )

    assert resp.status_code == 200
    assert resp.json()["grams"] == 135
    assert resp.json()["food_id"] == item["food_id"]
    reread = (await client.get(f"/api/diet-plans/{plan['id']}")).json()
    edited = next(
        i for d in reread["days"] for m in d["meals"] for i in m["items"] if i["id"] == item["id"]
    )
    assert edited["grams"] == 135


async def test_editing_the_food_of_an_item_recomputes_its_alternatives(
    registered_client, diet_candidates
):
    client, _user_id = registered_client
    plan, item = await _first_item(client)
    other = next(str(f) for f in diet_candidates if str(f) != item["food_id"])

    resp = await client.put(
        f"/api/diet-plans/{plan['id']}/items/{item['id']}", json={"food_id": other}
    )

    assert resp.status_code == 200
    assert resp.json()["food_id"] == other
    assert other not in {a["food_id"] for a in resp.json()["alternatives"]}


async def test_an_item_cannot_be_edited_into_a_food_the_user_must_avoid(
    registered_client, diet_candidates, superuser_conn
):
    client, _user_id = registered_client
    plan, item = await _first_item(client)
    forbidden = next(str(f) for f in diet_candidates if str(f) != item["food_id"])
    await client.post("/api/restrictions", json={"kind": "banned_food", "food_id": forbidden})

    resp = await client.put(
        f"/api/diet-plans/{plan['id']}/items/{item['id']}", json={"food_id": forbidden}
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "RESTRICTED_FOOD"


async def test_editing_an_item_validates_its_input(registered_client, diet_candidates):
    import uuid

    client, _user_id = registered_client
    plan, item = await _first_item(client)
    url = f"/api/diet-plans/{plan['id']}/items/{item['id']}"

    nothing = await client.put(url, json={})
    assert nothing.status_code == 422
    assert nothing.json()["error"]["code"] == "NOTHING_TO_UPDATE"
    assert (await client.put(url, json={"grams": 0})).status_code == 422
    assert (await client.put(url, json={"food_id": str(uuid.uuid4())})).status_code == 404
    unknown_item = await client.put(
        f"/api/diet-plans/{plan['id']}/items/{uuid.uuid4()}", json={"grams": 50}
    )
    assert unknown_item.status_code == 404
    assert unknown_item.json()["error"]["code"] == "PLAN_ITEM_NOT_FOUND"


async def test_another_user_cannot_edit_my_plan_items(
    registered_client, fresh_client, diet_candidates
):
    client, _user_id = registered_client
    plan, item = await _first_item(client)
    other_client, _ = fresh_client

    resp = await other_client.put(
        f"/api/diet-plans/{plan['id']}/items/{item['id']}", json={"grams": 50}
    )

    assert resp.status_code == 404
