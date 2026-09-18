"""Despensa del usuario (sección 6.4, Fase 7)."""

import uuid

import pytest

pytestmark = pytest.mark.asyncio


async def test_add_and_list_pantry_item(registered_client, test_food):
    client, _ = registered_client
    resp = await client.post(
        "/api/pantry", json={"food_id": str(test_food), "quantity_g": 500}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["food_id"] == str(test_food)
    assert body["food_name"] == "Pechuga de pollo de prueba"
    assert body["quantity_g"] == 500.0
    assert body["expires_on"] is None

    listed = await client.get("/api/pantry")
    assert len(listed.json()) == 1


async def test_adding_same_food_twice_sums_quantity(registered_client, test_food):
    client, _ = registered_client
    await client.post("/api/pantry", json={"food_id": str(test_food), "quantity_g": 300})
    resp = await client.post("/api/pantry", json={"food_id": str(test_food), "quantity_g": 200})
    assert resp.status_code == 201
    assert resp.json()["quantity_g"] == 500.0

    listed = await client.get("/api/pantry")
    assert len(listed.json()) == 1  # no duplicó la fila


async def test_add_pantry_item_unknown_food_is_404(registered_client):
    client, _ = registered_client
    resp = await client.post("/api/pantry", json={"food_id": str(uuid.uuid4()), "quantity_g": 100})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "FOOD_NOT_FOUND"


async def test_patch_updates_quantity_and_expiry(registered_client, test_food):
    client, _ = registered_client
    created = await client.post("/api/pantry", json={"food_id": str(test_food), "quantity_g": 100})
    item_id = created.json()["id"]

    resp = await client.patch(
        f"/api/pantry/{item_id}", json={"quantity_g": 250, "expires_on": "2026-12-31"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["quantity_g"] == 250.0
    assert body["expires_on"] == "2026-12-31"


async def test_delete_pantry_item(registered_client, test_food):
    client, _ = registered_client
    created = await client.post("/api/pantry", json={"food_id": str(test_food), "quantity_g": 100})
    item_id = created.json()["id"]

    resp = await client.delete(f"/api/pantry/{item_id}")
    assert resp.status_code == 204

    listed = await client.get("/api/pantry")
    assert listed.json() == []


async def test_delete_nonexistent_pantry_item_is_404(registered_client):
    client, _ = registered_client
    resp = await client.delete(f"/api/pantry/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PANTRY_ITEM_NOT_FOUND"


async def test_pantry_cross_user_isolation(registered_client, superuser_conn, test_food):
    """R3/R11 — RLS bloquea el acceso a la despensa de otro usuario incluso
    antes de la comprobación explícita de `user_id` en el router."""
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text

    from myfood.main import app

    client, _ = registered_client
    created = await client.post("/api/pantry", json={"food_id": str(test_food), "quantity_g": 100})
    item_id = created.json()["id"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as other_client:
        email = f"other-{uuid.uuid4()}@test.myfood"
        other_resp = await other_client.post(
            "/api/auth/register",
            json={"email": email, "password": "correcthorse123", "display_name": "Other"},
        )
        other_id = other_resp.json()["id"]

        other_list = await other_client.get("/api/pantry")
        assert other_list.json() == []

        patch_resp = await other_client.patch(f"/api/pantry/{item_id}", json={"quantity_g": 999})
        assert patch_resp.status_code == 404

        delete_resp = await other_client.delete(f"/api/pantry/{item_id}")
        assert delete_resp.status_code == 404

    await superuser_conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": other_id})
    await superuser_conn.commit()

    listed = await client.get("/api/pantry")
    assert len(listed.json()) == 1
