"""Restricciones alimentarias del usuario y catálogo de alérgenos
(sección 6.1) — `routers/restrictions.py`."""

import uuid

import pytest

pytestmark = pytest.mark.asyncio


async def test_list_allergens_returns_the_14_eu_regulated_allergens(registered_client):
    client, _ = registered_client
    resp = await client.get("/api/allergens")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 14
    codes = {item["code"] for item in items}
    assert "gluten" in codes
    assert "crustaceos" in codes
    assert all(item["name_es"] for item in items)


async def test_list_allergens_requires_auth():
    from httpx import ASGITransport, AsyncClient

    from myfood.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        resp = await client.get("/api/allergens")
        assert resp.status_code == 401


async def test_create_and_list_allergen_restriction(registered_client):
    client, _ = registered_client

    created = await client.post(
        "/api/restrictions",
        json={"kind": "allergen", "allergen_code": "gluten", "note": "Celiaquía"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["kind"] == "allergen"
    assert body["allergen_code"] == "gluten"
    assert body["allergen_name"]
    assert body["food_id"] is None
    assert body["note"] == "Celiaquía"

    listed = await client.get("/api/restrictions")
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == body["id"]
    assert items[0]["allergen_name"] == body["allergen_name"]


async def test_create_disliked_food_restriction_resolves_food_name(registered_client, test_food):
    client, _ = registered_client

    created = await client.post(
        "/api/restrictions", json={"kind": "disliked_food", "food_id": str(test_food)}
    )
    assert created.status_code == 201
    body = created.json()
    assert body["food_id"] == str(test_food)
    assert body["food_name"] == "Pechuga de pollo de prueba"
    assert body["allergen_code"] is None

    listed = await client.get("/api/restrictions")
    items = listed.json()["items"]
    assert items[0]["food_name"] == "Pechuga de pollo de prueba"


async def test_intolerance_accepts_either_allergen_code_or_food_id(registered_client, test_food):
    client, _ = registered_client

    by_allergen = await client.post(
        "/api/restrictions", json={"kind": "intolerance", "allergen_code": "lacteos"}
    )
    assert by_allergen.status_code == 201
    assert by_allergen.json()["allergen_code"] == "lacteos"

    by_food = await client.post(
        "/api/restrictions", json={"kind": "intolerance", "food_id": str(test_food)}
    )
    assert by_food.status_code == 201
    assert by_food.json()["food_id"] == str(test_food)


async def test_delete_restriction(registered_client):
    client, _ = registered_client
    created = await client.post(
        "/api/restrictions", json={"kind": "allergen", "allergen_code": "soja"}
    )
    restriction_id = created.json()["id"]

    deleted = await client.delete(f"/api/restrictions/{restriction_id}")
    assert deleted.status_code == 204

    listed = await client.get("/api/restrictions")
    assert listed.json()["items"] == []

    missing = await client.delete(f"/api/restrictions/{restriction_id}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "RESTRICTION_NOT_FOUND"


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "allergen"},  # falta allergen_code
        {"kind": "allergen", "allergen_code": "gluten", "food_id": str(uuid.uuid4())},  # ambos
        {"kind": "disliked_food"},  # falta food_id
        {"kind": "disliked_food", "food_id": str(uuid.uuid4()), "allergen_code": "gluten"},
        {"kind": "banned_food"},  # falta food_id
        {"kind": "intolerance"},  # ninguno de los dos
        {"kind": "intolerance", "allergen_code": "gluten", "food_id": str(uuid.uuid4())},  # ambos
        {"kind": "not_a_real_kind", "food_id": str(uuid.uuid4())},
    ],
)
async def test_create_restriction_validation_errors(registered_client, payload):
    client, _ = registered_client
    resp = await client.post("/api/restrictions", json=payload)
    assert resp.status_code == 422


async def test_create_restriction_unknown_allergen_is_404(registered_client):
    client, _ = registered_client
    resp = await client.post(
        "/api/restrictions", json={"kind": "allergen", "allergen_code": "no_existe"}
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "ALLERGEN_NOT_FOUND"


async def test_create_restriction_unknown_food_is_404(registered_client):
    client, _ = registered_client
    resp = await client.post(
        "/api/restrictions", json={"kind": "banned_food", "food_id": str(uuid.uuid4())}
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "FOOD_NOT_FOUND"


async def test_restrictions_cross_user_isolation(registered_client, superuser_conn):
    """R3 — ningún endpoint devuelve ni modifica restricciones de otro usuario."""
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text

    from myfood.main import app

    client, _ = registered_client
    created = await client.post(
        "/api/restrictions", json={"kind": "allergen", "allergen_code": "mostaza"}
    )
    restriction_id = created.json()["id"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as other_client:
        email = f"other-{uuid.uuid4()}@test.myfood"
        other_resp = await other_client.post(
            "/api/auth/register",
            json={"email": email, "password": "correcthorse123", "display_name": "Other"},
        )
        other_id = other_resp.json()["id"]

        other_list = await other_client.get("/api/restrictions")
        assert other_list.json()["items"] == []

        delete_resp = await other_client.delete(f"/api/restrictions/{restriction_id}")
        assert delete_resp.status_code == 404

    await superuser_conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": other_id})
    await superuser_conn.commit()

    # La restricción del usuario original sigue intacta (el intento de
    # borrado del otro usuario no debe haber tenido ningún efecto).
    still_there = await client.get("/api/restrictions")
    assert len(still_there.json()["items"]) == 1
