"""Modo familia (Fase 7): hogar compartido + despensa y lista de la compra
visibles/editables entre miembros, con RLS ampliada (migración 0011)."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from myfood.main import app

pytestmark = pytest.mark.asyncio


async def _new_client() -> tuple[AsyncClient, str]:
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="https://test")
    email = f"household-{uuid.uuid4()}@test.myfood"
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "correcthorse123", "display_name": "Household Test"},
    )
    return client, resp.json()["id"]


async def _cleanup_users(superuser_conn, *user_ids: str) -> None:
    for uid in user_ids:
        await superuser_conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": uid})
    await superuser_conn.commit()


async def test_create_household_returns_invite_code(registered_client):
    client, _ = registered_client
    resp = await client.post("/api/household", json={"name": "Casa"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Casa"
    assert len(body["invite_code"]) >= 6
    assert len(body["members"]) == 1


async def test_create_household_twice_is_422(registered_client):
    client, _ = registered_client
    await client.post("/api/household", json={"name": "Casa"})
    resp = await client.post("/api/household", json={"name": "Otra casa"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "ALREADY_IN_HOUSEHOLD"


async def test_get_household_returns_null_when_not_in_one(registered_client):
    client, _ = registered_client
    resp = await client.get("/api/household")
    assert resp.status_code == 200
    assert resp.json() is None


async def test_join_with_unknown_code_is_404(registered_client):
    client, _ = registered_client
    resp = await client.post("/api/household/join", json={"invite_code": "NOEXISTE"})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "INVITE_CODE_NOT_FOUND"


async def test_leave_without_household_is_422(registered_client):
    client, _ = registered_client
    resp = await client.post("/api/household/leave")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "NOT_IN_HOUSEHOLD"


async def test_join_and_leave_household(superuser_conn):
    client_a, user_a = await _new_client()
    client_b, user_b = await _new_client()
    try:
        created = await client_a.post("/api/household", json={"name": "Casa compartida"})
        invite_code = created.json()["invite_code"]

        joined = await client_b.post("/api/household/join", json={"invite_code": invite_code})
        assert joined.status_code == 200
        assert len(joined.json()["members"]) == 2

        mine = await client_a.get("/api/household")
        member_ids = {m["user_id"] for m in mine.json()["members"]}
        assert member_ids == {user_a, user_b}

        left = await client_b.post("/api/household/leave")
        assert left.status_code == 204

        after = await client_a.get("/api/household")
        assert len(after.json()["members"]) == 1

        # El hogar desaparece cuando se va el último miembro.
        left_a = await client_a.post("/api/household/leave")
        assert left_a.status_code == 204
        assert (await client_a.get("/api/household")).json() is None
    finally:
        await client_a.aclose()
        await client_b.aclose()
        await _cleanup_users(superuser_conn, user_a, user_b)


async def test_join_invite_code_is_case_insensitive(superuser_conn):
    client_a, user_a = await _new_client()
    client_b, user_b = await _new_client()
    try:
        created = await client_a.post("/api/household", json={"name": "Casa"})
        invite_code = created.json()["invite_code"]

        joined = await client_b.post(
            "/api/household/join", json={"invite_code": invite_code.lower()}
        )
        assert joined.status_code == 200
    finally:
        await client_a.aclose()
        await client_b.aclose()
        await _cleanup_users(superuser_conn, user_a, user_b)


async def test_pantry_shared_between_household_members(superuser_conn, test_food):
    client_a, user_a = await _new_client()
    client_b, user_b = await _new_client()
    client_stranger, user_stranger = await _new_client()
    try:
        created = await client_a.post("/api/household", json={"name": "Casa"})
        invite_code = created.json()["invite_code"]
        await client_b.post("/api/household/join", json={"invite_code": invite_code})

        added = await client_a.post(
            "/api/pantry", json={"food_id": str(test_food), "quantity_g": 500}
        )
        item_id = added.json()["id"]

        # B (mismo hogar) lo ve, marcado como no suyo.
        pantry_b = (await client_b.get("/api/pantry")).json()
        assert len(pantry_b) == 1
        assert pantry_b[0]["is_mine"] is False
        assert pantry_b[0]["owner_name"] == "Household Test"

        # El desconocido (sin hogar) no ve nada.
        pantry_stranger = (await client_stranger.get("/api/pantry")).json()
        assert pantry_stranger == []

        # B puede VER el artículo de A, pero no editarlo ni borrarlo — la
        # despensa comparte visibilidad, no propiedad.
        patch_resp = await client_b.patch(f"/api/pantry/{item_id}", json={"quantity_g": 999})
        assert patch_resp.status_code == 404
        delete_resp = await client_b.delete(f"/api/pantry/{item_id}")
        assert delete_resp.status_code == 404

        # A sigue viendo su propio artículo intacto.
        pantry_a = (await client_a.get("/api/pantry")).json()
        assert pantry_a[0]["quantity_g"] == 500.0
        assert pantry_a[0]["is_mine"] is True
    finally:
        await client_a.aclose()
        await client_b.aclose()
        await client_stranger.aclose()
        await _cleanup_users(superuser_conn, user_a, user_b, user_stranger)


async def test_shopping_list_is_collaborative_within_household(superuser_conn):
    client_a, user_a = await _new_client()
    client_b, user_b = await _new_client()
    try:
        created = await client_a.post("/api/household", json={"name": "Casa"})
        invite_code = created.json()["invite_code"]
        await client_b.post("/api/household/join", json={"invite_code": invite_code})

        added = await client_a.post("/api/shopping-list", json={"free_text": "Leche"})
        item_id = added.json()["id"]
        assert added.json()["owner_name"] == "Household Test"

        # B ve el artículo de A y SÍ puede marcarlo como comprado (lista
        # colaborativa, a diferencia de la despensa).
        listed_b = (await client_b.get("/api/shopping-list")).json()["items"]
        assert len(listed_b) == 1
        assert listed_b[0]["is_mine"] is False

        checked = await client_b.patch(f"/api/shopping-list/{item_id}", json={"is_checked": True})
        assert checked.status_code == 200
        assert checked.json()["is_checked"] is True

        # Y también puede borrarlo (o limpiar completados) tras la compra.
        clear_resp = await client_b.delete("/api/shopping-list/checked")
        assert clear_resp.status_code == 204
        assert (await client_a.get("/api/shopping-list")).json()["items"] == []
    finally:
        await client_a.aclose()
        await client_b.aclose()
        await _cleanup_users(superuser_conn, user_a, user_b)


async def test_shopping_list_not_visible_outside_household(superuser_conn):
    client_a, user_a = await _new_client()
    client_stranger, user_stranger = await _new_client()
    try:
        await client_a.post("/api/shopping-list", json={"free_text": "Secreto"})

        listed_stranger = (await client_stranger.get("/api/shopping-list")).json()["items"]
        assert listed_stranger == []
    finally:
        await client_a.aclose()
        await client_stranger.aclose()
        await _cleanup_users(superuser_conn, user_a, user_stranger)
