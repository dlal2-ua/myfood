"""Tests del flujo de escaneo (documento 2, sección 11.2): BD local -> caché
de negativos -> OFF en vivo -> alta manual. `fetch_product` se sustituye por
un doble de prueba (nunca se toca la red real desde estos tests)."""

import uuid

import pytest_asyncio
from sqlalchemy import text

from myfood.cache import _redis
from myfood.off_client import OffProduct


@pytest_asyncio.fixture(autouse=True)
async def _clear_barcode_cache():
    """Evita que el estado de un test (caché de negativos en Redis) se
    filtre al siguiente. Borra solo las claves de este caché (`off:barcode:*`)
    — nunca un `flushdb()`, que también se cargaría las sesiones reales que
    crea `registered_client` en el mismo Redis (sección 22)."""
    async for key in _redis.scan_iter(match="off:barcode:*"):
        await _redis.delete(key)
    yield


async def test_barcode_found_locally_skips_off(monkeypatch, registered_client, superuser_conn):
    client, _user_id = registered_client
    ean = "8400000000017"
    food_id = uuid.uuid4()
    await superuser_conn.execute(
        text(
            "INSERT INTO foods (id, kind, source, source_id, license, barcode_ean, "
            "name_es, quality_rank) "
            "VALUES (:id, 'branded', 'off', :ean, 'ODbL', :ean, 'Producto local', 5)"
        ),
        {"id": str(food_id), "ean": ean},
    )
    await superuser_conn.execute(
        text(
            "INSERT INTO food_nutrients (food_id, kcal_100g, protein_100g, fat_100g, carbs_100g) "
            "VALUES (:id, 100, 5, 2, 10)"
        ),
        {"id": str(food_id)},
    )
    await superuser_conn.commit()

    called = {"n": 0}

    async def _should_not_be_called(*args, **kwargs):
        called["n"] += 1
        return None

    monkeypatch.setattr("myfood.routers.foods.fetch_product", _should_not_be_called)

    resp = await client.get(f"/api/foods/barcode/{ean}")
    assert resp.status_code == 200
    assert resp.json()["name_es"] == "Producto local"
    assert called["n"] == 0

    await superuser_conn.execute(text("DELETE FROM foods WHERE id = :id"), {"id": str(food_id)})
    await superuser_conn.commit()


async def test_barcode_not_found_locally_falls_back_to_off(
    monkeypatch, registered_client, superuser_conn
):
    client, _user_id = registered_client
    ean = "8400000000024"

    async def _fake_fetch(barcode, client=None):
        assert barcode == ean
        return OffProduct(
            barcode_ean=ean,
            name_es="Producto de OFF",
            name_en=None,
            brand="Marca Test",
            category=None,
            serving_size_g=None,
            serving_label=None,
            nutriscore_grade="b",
            nova_group=2,
            ecoscore_grade=None,
            kcal_100g=150,
            protein_100g=10,
            fat_100g=5,
            saturated_100g=None,
            carbs_100g=20,
            sugars_100g=None,
            fiber_100g=None,
            salt_100g=None,
            micros={},
        )

    monkeypatch.setattr("myfood.routers.foods.fetch_product", _fake_fetch)

    resp = await client.get(f"/api/foods/barcode/{ean}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name_es"] == "Producto de OFF"
    assert body["kcal_100g"] == 150
    assert body["source"] == "off"

    row = await superuser_conn.execute(
        text("SELECT id FROM foods WHERE barcode_ean = :ean"), {"ean": ean}
    )
    food_id = row.scalar_one()

    await superuser_conn.execute(text("DELETE FROM foods WHERE id = :id"), {"id": food_id})
    await superuser_conn.commit()


async def test_barcode_not_found_anywhere_returns_404_and_caches_negative(
    monkeypatch, registered_client
):
    client, _user_id = registered_client
    ean = "8400000000031"
    called = {"n": 0}

    async def _fake_fetch(barcode, client=None):
        called["n"] += 1
        return None

    monkeypatch.setattr("myfood.routers.foods.fetch_product", _fake_fetch)

    resp1 = await client.get(f"/api/foods/barcode/{ean}")
    assert resp1.status_code == 404
    assert resp1.json()["error"]["code"] == "FOOD_NOT_FOUND_BY_BARCODE"

    resp2 = await client.get(f"/api/foods/barcode/{ean}")
    assert resp2.status_code == 404
    assert called["n"] == 1  # el segundo intento vino de la caché de negativos


async def test_barcode_invalid_format_is_rejected(registered_client):
    client, _user_id = registered_client
    resp = await client.get("/api/foods/barcode/not-a-barcode")
    assert resp.status_code == 422


async def test_manual_food_creation(registered_client, superuser_conn):
    client, _user_id = registered_client
    resp = await client.post(
        "/api/foods/manual",
        json={
            "name_es": "Tupper casero de lentejas",
            "kcal_100g": 120,
            "protein_100g": 8,
            "fat_100g": 3,
            "carbs_100g": 15,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["kind"] == "user"
    assert body["quality_rank"] == 6

    await superuser_conn.execute(text("DELETE FROM foods WHERE id = :id"), {"id": body["id"]})
    await superuser_conn.commit()


async def test_manual_food_macros_exceeding_100g_rejected(registered_client):
    client, _user_id = registered_client
    resp = await client.post(
        "/api/foods/manual",
        json={
            "name_es": "Macros imposibles",
            "kcal_100g": 400,
            "protein_100g": 60,
            "fat_100g": 30,
            "carbs_100g": 30,
        },
    )
    assert resp.status_code == 422


async def test_manual_food_with_barcode_is_idempotent(registered_client, superuser_conn):
    client, _user_id = registered_client
    ean = "8400000000048"
    payload = {
        "barcode_ean": ean,
        "name_es": "Producto con código",
        "kcal_100g": 200,
        "protein_100g": 5,
        "fat_100g": 5,
        "carbs_100g": 20,
    }

    resp1 = await client.post("/api/foods/manual", json=payload)
    resp2 = await client.post("/api/foods/manual", json=payload)
    assert resp1.status_code == 201
    assert resp2.status_code == 201
    assert resp1.json()["id"] == resp2.json()["id"]

    await superuser_conn.execute(
        text("DELETE FROM foods WHERE id = :id"), {"id": resp1.json()["id"]}
    )
    await superuser_conn.commit()
