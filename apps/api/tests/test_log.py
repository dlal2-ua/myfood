"""Registro diario de comidas (sección 7.3) — snapshot nutricional congelado."""

from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.asyncio


async def test_log_food_computes_snapshot_from_grams(registered_client, test_food):
    client, _ = registered_client
    today = date.today().isoformat()

    resp = await client.post(
        "/api/log/food",
        json={
            "log_date": today,
            "meal_type": "lunch",
            "food_id": str(test_food),
            "grams": 150,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["kcal"] == 247.5  # 165 * 1.5
    assert body["protein_g"] == 46.5  # 31 * 1.5
    assert body["fat_g"] == 5.4  # 3.6 * 1.5
    assert body["carbs_g"] == 0


async def test_log_food_unknown_food_is_404(registered_client):
    import uuid

    client, _ = registered_client
    resp = await client.post(
        "/api/log/food",
        json={
            "log_date": date.today().isoformat(),
            "meal_type": "lunch",
            "food_id": str(uuid.uuid4()),
            "grams": 100,
        },
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "FOOD_NOT_FOUND"


async def test_get_day_log_totals_update_after_adding_entries(registered_client, test_food):
    client, _ = registered_client
    today = date.today().isoformat()

    await client.post(
        "/api/log/food",
        json={"log_date": today, "meal_type": "breakfast", "food_id": str(test_food), "grams": 100},
    )
    await client.post(
        "/api/log/food",
        json={"log_date": today, "meal_type": "lunch", "food_id": str(test_food), "grams": 200},
    )

    resp = await client.get("/api/log", params={"date": today})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["food"]) == 2
    # 165*1 + 165*2 = 495
    assert body["totals"]["kcal"] == 495.0
    assert body["totals"]["protein_g"] == pytest.approx(93.0)


async def test_get_day_log_empty_day_has_zero_totals(registered_client):
    client, _ = registered_client
    resp = await client.get("/api/log", params={"date": "2020-01-01"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["food"] == []
    assert body["totals"] == {"kcal": 0, "protein_g": 0, "fat_g": 0, "carbs_g": 0}


async def test_patch_grams_recomputes_snapshot(registered_client, test_food):
    client, _ = registered_client
    today = date.today().isoformat()
    created = await client.post(
        "/api/log/food",
        json={"log_date": today, "meal_type": "dinner", "food_id": str(test_food), "grams": 100},
    )
    entry_id = created.json()["id"]

    resp = await client.patch(f"/api/log/food/{entry_id}", json={"grams": 50})
    assert resp.status_code == 200
    body = resp.json()
    assert body["grams"] == 50
    assert body["kcal"] == 82.5  # 165 * 0.5


async def test_patch_meal_type_only(registered_client, test_food):
    client, _ = registered_client
    today = date.today().isoformat()
    created = await client.post(
        "/api/log/food",
        json={"log_date": today, "meal_type": "breakfast", "food_id": str(test_food), "grams": 100},
    )
    entry_id = created.json()["id"]

    resp = await client.patch(f"/api/log/food/{entry_id}", json={"meal_type": "dinner"})
    assert resp.status_code == 200
    assert resp.json()["meal_type"] == "dinner"
    assert resp.json()["kcal"] == 165.0  # sin cambios


async def test_delete_log_food_removes_entry(registered_client, test_food):
    client, _ = registered_client
    today = date.today().isoformat()
    created = await client.post(
        "/api/log/food",
        json={"log_date": today, "meal_type": "lunch", "food_id": str(test_food), "grams": 100},
    )
    entry_id = created.json()["id"]

    resp = await client.delete(f"/api/log/food/{entry_id}")
    assert resp.status_code == 204

    day = await client.get("/api/log", params={"date": today})
    assert day.json()["food"] == []


async def test_patch_and_delete_another_users_entry_is_404(
    registered_client, test_food, superuser_conn
):
    """R3 — ningún endpoint devuelve ni modifica datos de otro usuario."""
    from httpx import ASGITransport, AsyncClient

    from myfood.main import app

    client, _ = registered_client
    today = date.today().isoformat()
    created = await client.post(
        "/api/log/food",
        json={"log_date": today, "meal_type": "lunch", "food_id": str(test_food), "grams": 100},
    )
    entry_id = created.json()["id"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as other_client:
        import uuid

        email = f"other-{uuid.uuid4()}@test.myfood"
        other_resp = await other_client.post(
            "/api/auth/register",
            json={"email": email, "password": "correcthorse123", "display_name": "Other"},
        )
        other_id = other_resp.json()["id"]

        patch_resp = await other_client.patch(f"/api/log/food/{entry_id}", json={"grams": 999})
        assert patch_resp.status_code == 404

        delete_resp = await other_client.delete(f"/api/log/food/{entry_id}")
        assert delete_resp.status_code == 404

    from sqlalchemy import text

    await superuser_conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": other_id})
    await superuser_conn.commit()

    # el registro original sigue intacto
    day = await client.get("/api/log", params={"date": today})
    assert len(day.json()["food"]) == 1


async def test_copy_day_duplicates_entries(registered_client, test_food):
    client, _ = registered_client
    today = date.today()
    tomorrow = today + timedelta(days=1)

    await client.post(
        "/api/log/food",
        json={
            "log_date": today.isoformat(),
            "meal_type": "lunch",
            "food_id": str(test_food),
            "grams": 100,
        },
    )

    resp = await client.post(
        "/api/log/copy-day",
        params={"from_date": today.isoformat(), "to_date": tomorrow.isoformat()},
    )
    assert resp.status_code == 201
    assert len(resp.json()) == 1

    day = await client.get("/api/log", params={"date": tomorrow.isoformat()})
    assert len(day.json()["food"]) == 1
    assert day.json()["food"][0]["kcal"] == 165.0


async def test_log_food_with_client_id_is_idempotent(registered_client, test_food):
    import uuid

    client, _ = registered_client
    client_id = str(uuid.uuid4())
    payload = {
        "log_date": date.today().isoformat(),
        "meal_type": "lunch",
        "food_id": str(test_food),
        "grams": 100,
        "client_id": client_id,
    }

    first = await client.post("/api/log/food", json=payload)
    second = await client.post("/api/log/food", json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == client_id == second.json()["id"]
    day = await client.get(f"/api/log?date={payload['log_date']}")
    assert len([e for e in day.json()["food"] if e["id"] == client_id]) == 1


async def test_log_food_client_id_of_another_user_is_a_conflict(
    registered_client, fresh_client, test_food
):
    import uuid

    client, _ = registered_client
    client_id = str(uuid.uuid4())
    payload = {
        "log_date": date.today().isoformat(),
        "meal_type": "lunch",
        "food_id": str(test_food),
        "grams": 100,
        "client_id": client_id,
    }
    assert (await client.post("/api/log/food", json=payload)).status_code == 201

    other, _ = fresh_client
    resp = await other.post("/api/log/food", json=payload)

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "CLIENT_ID_CONFLICT"


async def test_copy_day_onto_itself_is_rejected(registered_client):
    client, _ = registered_client
    today = date.today().isoformat()

    resp = await client.post("/api/log/copy-day", params={"from_date": today, "to_date": today})

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "SAME_DATE"


async def test_the_day_log_includes_the_food_name(registered_client, test_food):
    client, _ = registered_client
    today = date.today().isoformat()
    await client.post(
        "/api/log/food",
        json={"log_date": today, "meal_type": "lunch", "food_id": str(test_food), "grams": 100},
    )
    day = (await client.get("/api/log", params={"date": today})).json()
    assert day["food"][0]["food_name"] == "Pechuga de pollo de prueba"
