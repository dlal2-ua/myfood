"""Lista de la compra manual (sección 6.4)."""

import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio


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
