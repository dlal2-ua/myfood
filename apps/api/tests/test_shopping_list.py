"""Lista de la compra manual (sección 6.4) y generada desde un plan con
descuento de despensa (Fase 7)."""

import uuid
from collections import defaultdict

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio


async def _complete_profile(client):
    await client.put(
        "/api/profile",
        json={"sex": "male", "birth_date": "1995-01-01", "height_cm": 180, "meals_per_day": 3},
    )
    await client.post("/api/measurements", json={"measured_on": "2026-01-10", "weight_kg": 80})


async def _generate_plan_and_totals(client) -> tuple[str, dict[str, float]]:
    """Genera un plan de 1 día real (mismo `diet_candidates` que
    test_diet_plans.py) y devuelve `(plan_id, {food_id: gramos totales})`."""
    await _complete_profile(client)
    resp = await client.post(
        "/api/diet-plans/generate", json={"name": "Plan para la compra", "num_days": 1}
    )
    assert resp.status_code == 201
    plan = resp.json()

    totals: dict[str, float] = defaultdict(float)
    for day in plan["days"]:
        for meal in day["meals"]:
            for item in meal["items"]:
                if item["food_id"] is not None:
                    totals[item["food_id"]] += item["grams"]
    return plan["id"], dict(totals)


async def test_add_item_with_food(registered_client, test_food):
    client, _ = registered_client

    resp = await client.post(
        "/api/shopping-list",
        json={"food_id": str(test_food), "quantity_g": 500, "category": "Carnes"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["food_id"] == str(test_food)
    assert body["food_name"] == "Pechuga de pollo de prueba"
    assert body["quantity_g"] == 500.0
    assert body["category"] == "Carnes"
    assert body["is_checked"] is False

    listed = await client.get("/api/shopping-list")
    assert len(listed.json()["items"]) == 1


async def test_add_item_with_free_text(registered_client):
    client, _ = registered_client
    resp = await client.post("/api/shopping-list", json={"free_text": "Papel de aluminio"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["free_text"] == "Papel de aluminio"
    assert body["food_id"] is None
    assert body["food_name"] is None


async def test_add_item_requires_exactly_one_of_food_or_text(registered_client, test_food):
    client, _ = registered_client

    neither = await client.post("/api/shopping-list", json={"quantity_g": 100})
    assert neither.status_code == 422

    both = await client.post(
        "/api/shopping-list", json={"food_id": str(test_food), "free_text": "algo"}
    )
    assert both.status_code == 422


async def test_add_item_unknown_food_is_404(registered_client):
    client, _ = registered_client
    resp = await client.post("/api/shopping-list", json={"food_id": str(uuid.uuid4())})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "FOOD_NOT_FOUND"


async def test_patch_toggle_checked(registered_client):
    client, _ = registered_client
    created = await client.post("/api/shopping-list", json={"free_text": "Leche"})
    item_id = created.json()["id"]

    resp = await client.patch(f"/api/shopping-list/{item_id}", json={"is_checked": True})
    assert resp.status_code == 200
    assert resp.json()["is_checked"] is True

    resp2 = await client.patch(f"/api/shopping-list/{item_id}", json={"is_checked": False})
    assert resp2.json()["is_checked"] is False


async def test_patch_edit_quantity_and_category(registered_client, test_food):
    client, _ = registered_client
    created = await client.post(
        "/api/shopping-list", json={"food_id": str(test_food), "quantity_g": 200}
    )
    item_id = created.json()["id"]

    resp = await client.patch(
        f"/api/shopping-list/{item_id}", json={"quantity_g": 350, "category": "Nevera"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["quantity_g"] == 350.0
    assert body["category"] == "Nevera"


async def test_delete_item(registered_client):
    client, _ = registered_client
    created = await client.post("/api/shopping-list", json={"free_text": "Pan"})
    item_id = created.json()["id"]

    resp = await client.delete(f"/api/shopping-list/{item_id}")
    assert resp.status_code == 204

    listed = await client.get("/api/shopping-list")
    assert listed.json()["items"] == []


async def test_delete_nonexistent_item_is_404(registered_client):
    client, _ = registered_client
    resp = await client.delete(f"/api/shopping-list/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "SHOPPING_ITEM_NOT_FOUND"


async def test_clear_checked_removes_only_checked_items(registered_client):
    client, _ = registered_client
    a = await client.post("/api/shopping-list", json={"free_text": "A"})
    b = await client.post("/api/shopping-list", json={"free_text": "B"})
    c = await client.post("/api/shopping-list", json={"free_text": "C"})

    await client.patch(f"/api/shopping-list/{a.json()['id']}", json={"is_checked": True})
    await client.patch(f"/api/shopping-list/{c.json()['id']}", json={"is_checked": True})

    resp = await client.delete("/api/shopping-list/checked")
    assert resp.status_code == 204

    listed = await client.get("/api/shopping-list")
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == b.json()["id"]


async def test_list_unchecked_items_come_first(registered_client):
    client, _ = registered_client
    first = await client.post("/api/shopping-list", json={"free_text": "Primero"})
    await client.patch(f"/api/shopping-list/{first.json()['id']}", json={"is_checked": True})
    await client.post("/api/shopping-list", json={"free_text": "Segundo"})

    listed = await client.get("/api/shopping-list")
    items = listed.json()["items"]
    assert items[0]["is_checked"] is False
    assert items[-1]["is_checked"] is True


async def test_generate_from_plan_unknown_plan_is_404(registered_client):
    client, _ = registered_client
    resp = await client.post(f"/api/shopping-list/from-plan/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "DIET_PLAN_NOT_FOUND"


async def test_generate_from_plan_deducts_pantry_stock(registered_client, diet_candidates):
    """Criterio de aceptación de la Fase 7: 'Lista de la compra descuenta lo
    que ya hay en la despensa'. Se generan 3 escenarios reales a partir de un
    plan real: un alimento cubierto del todo por la despensa (no debe salir
    en la lista), uno cubierto a medias (sale solo lo que falta) y uno sin
    nada en la despensa (sale entero)."""
    client, _ = registered_client
    plan_id, totals = await _generate_plan_and_totals(client)
    assert len(totals) >= 2  # diet_candidates garantiza variedad de alimentos

    food_ids = list(totals)
    fully_covered = food_ids[0]
    partially_covered = food_ids[1] if len(food_ids) > 1 else None
    uncovered = food_ids[2] if len(food_ids) > 2 else None

    await client.post(
        "/api/pantry", json={"food_id": fully_covered, "quantity_g": totals[fully_covered] + 500}
    )
    if partially_covered is not None:
        half = round(totals[partially_covered] / 2, 2)
        await client.post("/api/pantry", json={"food_id": partially_covered, "quantity_g": half})

    resp = await client.post(f"/api/shopping-list/from-plan/{plan_id}")
    assert resp.status_code == 201
    items_by_food = {item["food_id"]: item for item in resp.json()["items"]}

    assert fully_covered not in items_by_food  # despensa ya cubre todo, no se compra
    if partially_covered is not None:
        expected_remaining = round(totals[partially_covered] - half, 2)
        assert items_by_food[partially_covered]["quantity_g"] == pytest.approx(
            expected_remaining, abs=0.05
        )
    if uncovered is not None:
        assert items_by_food[uncovered]["quantity_g"] == pytest.approx(
            totals[uncovered], abs=0.05
        )

    # Persistido de verdad, no solo en la respuesta.
    listed = await client.get("/api/shopping-list")
    assert len(listed.json()["items"]) == len(items_by_food)


async def test_generate_from_plan_is_idempotent(registered_client, diet_candidates):
    """Repetir la generación para el mismo plan no acumula artículos
    duplicados — regenera en limpio."""
    client, _ = registered_client
    plan_id, _totals = await _generate_plan_and_totals(client)

    first = await client.post(f"/api/shopping-list/from-plan/{plan_id}")
    second = await client.post(f"/api/shopping-list/from-plan/{plan_id}")
    assert len(first.json()["items"]) == len(second.json()["items"])

    listed = await client.get("/api/shopping-list")
    assert len(listed.json()["items"]) == len(second.json()["items"])


async def test_shopping_list_cross_user_isolation(registered_client, superuser_conn):
    """R3 — ningún endpoint devuelve ni modifica artículos de otro usuario."""
    from httpx import ASGITransport, AsyncClient

    from myfood.main import app

    client, _ = registered_client
    created = await client.post("/api/shopping-list", json={"free_text": "Secreto"})
    item_id = created.json()["id"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as other_client:
        email = f"other-{uuid.uuid4()}@test.myfood"
        other_resp = await other_client.post(
            "/api/auth/register",
            json={"email": email, "password": "correcthorse123", "display_name": "Other"},
        )
        other_id = other_resp.json()["id"]

        other_list = await other_client.get("/api/shopping-list")
        assert other_list.json()["items"] == []

        patch_resp = await other_client.patch(
            f"/api/shopping-list/{item_id}", json={"is_checked": True}
        )
        assert patch_resp.status_code == 404

        delete_resp = await other_client.delete(f"/api/shopping-list/{item_id}")
        assert delete_resp.status_code == 404

    await superuser_conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": other_id})
    await superuser_conn.commit()

    # el artículo original sigue intacto
    listed = await client.get("/api/shopping-list")
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["is_checked"] is False
