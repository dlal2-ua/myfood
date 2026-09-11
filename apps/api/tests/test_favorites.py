"""Favoritos y quick-add (sección 6.8)."""

import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio


async def test_add_favorite_and_list(registered_client, test_food):
    client, _ = registered_client

    resp = await client.post("/api/favorites", json={"food_id": str(test_food)})
    assert resp.status_code == 201
    body = resp.json()
    assert body["food_id"] == str(test_food)
    assert body["name_es"] == "Pechuga de pollo de prueba"
    assert body["kcal_100g"] == 165.0
    assert body["use_count"] == 0
    assert body["last_used_at"] is None

    listed = await client.get("/api/favorites")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["food_id"] == str(test_food)


async def test_add_favorite_unknown_food_is_404(registered_client):
    client, _ = registered_client
    resp = await client.post("/api/favorites", json={"food_id": str(uuid.uuid4())})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "FOOD_NOT_FOUND"


async def test_add_favorite_is_idempotent(registered_client, test_food):
    """Marcar la estrella dos veces no debe fallar ni duplicar la fila — y no
    infla use_count (eso solo ocurre vía POST /favorites/{food_id}/use)."""
    client, _ = registered_client

    first = await client.post("/api/favorites", json={"food_id": str(test_food)})
    second = await client.post("/api/favorites", json={"food_id": str(test_food)})
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["use_count"] == 0

    listed = await client.get("/api/favorites")
    assert len(listed.json()["items"]) == 1


async def test_use_favorite_increments_use_count(registered_client, test_food):
    client, _ = registered_client
    await client.post("/api/favorites", json={"food_id": str(test_food)})

    resp = await client.post(f"/api/favorites/{test_food}/use")
    assert resp.status_code == 200
    body = resp.json()
    assert body["use_count"] == 1
    assert body["last_used_at"] is not None

    resp2 = await client.post(f"/api/favorites/{test_food}/use")
    assert resp2.json()["use_count"] == 2


async def test_use_unfavorited_food_is_404(registered_client, test_food):
    client, _ = registered_client
    resp = await client.post(f"/api/favorites/{test_food}/use")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "FAVORITE_NOT_FOUND"


async def test_list_favorites_sorted_by_use_count_desc(registered_client, superuser_conn):
    client, _ = registered_client

    async def make_food(name: str) -> uuid.UUID:
        food_id = uuid.uuid4()
        await superuser_conn.execute(
            text(
                "INSERT INTO foods (id, kind, source, source_id, license, name_es, quality_rank) "
                "VALUES (:id, 'generic', 'test', :sid, 'CC0', :name, 1)"
            ),
            {"id": str(food_id), "sid": str(food_id), "name": name},
        )
        await superuser_conn.execute(
            text("INSERT INTO food_nutrients (food_id, kcal_100g) VALUES (:id, 100)"),
            {"id": str(food_id)},
        )
        await superuser_conn.commit()
        return food_id

    food_a = await make_food("Alimento A")
    food_b = await make_food("Alimento B")
    try:
        await client.post("/api/favorites", json={"food_id": str(food_a)})
        await client.post("/api/favorites", json={"food_id": str(food_b)})
        await client.post(f"/api/favorites/{food_b}/use")
        await client.post(f"/api/favorites/{food_b}/use")
        await client.post(f"/api/favorites/{food_a}/use")

        listed = await client.get("/api/favorites")
        items = listed.json()["items"]
        assert [i["food_id"] for i in items] == [str(food_b), str(food_a)]
        assert items[0]["use_count"] == 2
        assert items[1]["use_count"] == 1
    finally:
        await superuser_conn.execute(
            text("DELETE FROM foods WHERE id IN (:a, :b)"), {"a": str(food_a), "b": str(food_b)}
        )
        await superuser_conn.commit()


async def test_remove_favorite(registered_client, test_food):
    client, _ = registered_client
    await client.post("/api/favorites", json={"food_id": str(test_food)})

    resp = await client.delete(f"/api/favorites/{test_food}")
    assert resp.status_code == 204

    listed = await client.get("/api/favorites")
    assert listed.json()["items"] == []


async def test_remove_nonexistent_favorite_is_404(registered_client, test_food):
    client, _ = registered_client
    resp = await client.delete(f"/api/favorites/{test_food}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "FAVORITE_NOT_FOUND"


async def test_favorites_cross_user_isolation(registered_client, test_food, superuser_conn):
    """R3 — ningún endpoint devuelve ni modifica favoritos de otro usuario."""
    from httpx import ASGITransport, AsyncClient

    from myfood.main import app

    client, _ = registered_client
    await client.post("/api/favorites", json={"food_id": str(test_food)})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as other_client:
        email = f"other-{uuid.uuid4()}@test.myfood"
        other_resp = await other_client.post(
            "/api/auth/register",
            json={"email": email, "password": "correcthorse123", "display_name": "Other"},
        )
        other_id = other_resp.json()["id"]

        other_list = await other_client.get("/api/favorites")
        assert other_list.json()["items"] == []

        delete_resp = await other_client.delete(f"/api/favorites/{test_food}")
        assert delete_resp.status_code == 404

        use_resp = await other_client.post(f"/api/favorites/{test_food}/use")
        assert use_resp.status_code == 404

    await superuser_conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": other_id})
    await superuser_conn.commit()

    # el favorito original sigue intacto y sin usos
    listed = await client.get("/api/favorites")
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["use_count"] == 0
