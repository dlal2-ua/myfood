"""GET /foods/search y GET /foods/{id} (sección 7.2) contra Meilisearch real.

Indexa un alimento de prueba directamente (sin pasar por el ETL, que es un
proceso aparte) y espera a que la tarea de Meilisearch termine antes de
buscar — Meilisearch indexa de forma asíncrona.
"""

import asyncio
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from myfood.config import get_settings

settings = get_settings()
pytestmark = pytest.mark.asyncio


def _meili_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.meili_master_key:
        headers["Authorization"] = f"Bearer {settings.meili_master_key}"
    return headers


async def _wait_task(client: httpx.AsyncClient, task_uid: int) -> None:
    for _ in range(50):
        resp = await client.get(f"/tasks/{task_uid}")
        if resp.json()["status"] in ("succeeded", "failed"):
            return
        await asyncio.sleep(0.1)


@pytest_asyncio.fixture
async def indexed_food(superuser_conn):
    food_id = uuid.uuid4()
    name = f"Alimento de prueba pechuga {food_id}"
    await superuser_conn.execute(
        text(
            "INSERT INTO foods (id, kind, source, source_id, license, name_es, quality_rank) "
            "VALUES (:id, 'generic', 'test', :sid, 'CC0', :name, 1)"
        ),
        {"id": str(food_id), "sid": str(food_id), "name": name},
    )
    await superuser_conn.execute(
        text(
            "INSERT INTO food_nutrients (food_id, kcal_100g, protein_100g) "
            "VALUES (:id, 165, 31)"
        ),
        {"id": str(food_id)},
    )
    await superuser_conn.commit()

    async with httpx.AsyncClient(
        base_url=settings.meili_url, headers=_meili_headers(), timeout=10
    ) as client:
        doc = {
            "id": str(food_id),
            "name_es": name,
            "name_en": None,
            "brand": None,
            "kind": "generic",
            "category": "test",
            "quality_rank": 1,
            "source": "test",
            "kcal_100g": 165.0,
            "protein_100g": 31.0,
            "has_image": False,
        }
        resp = await client.post("/indexes/foods/documents?primaryKey=id", json=[doc])
        await _wait_task(client, resp.json()["taskUid"])

    yield food_id, name

    async with httpx.AsyncClient(
        base_url=settings.meili_url, headers=_meili_headers(), timeout=10
    ) as client:
        await client.delete(f"/indexes/foods/documents/{food_id}")
    await superuser_conn.execute(text("DELETE FROM foods WHERE id = :id"), {"id": str(food_id)})
    await superuser_conn.commit()


async def test_search_finds_indexed_food(registered_client, indexed_food):
    client, _ = registered_client
    food_id, name = indexed_food

    resp = await client.get("/api/foods/search", params={"q": "pechuga de prueba"})
    assert resp.status_code == 200
    body = resp.json()
    ids = [item["id"] for item in body["items"]]
    assert str(food_id) in ids
    hit = next(item for item in body["items"] if item["id"] == str(food_id))
    assert hit["name_es"] == name
    assert hit["kcal_100g"] == 165.0
    assert hit["image_url"] is None  # has_image=False


async def test_search_requires_authentication():
    from httpx import ASGITransport, AsyncClient

    from myfood.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        resp = await client.get("/api/foods/search", params={"q": "pollo"})
    assert resp.status_code == 401


async def test_get_food_detail(registered_client, indexed_food):
    client, _ = registered_client
    food_id, name = indexed_food

    resp = await client.get(f"/api/foods/{food_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name_es"] == name
    assert body["kcal_100g"] == 165.0
    assert body["protein_100g"] == 31.0
    assert body["source"] == "test"


async def test_get_food_detail_not_found(registered_client):
    client, _ = registered_client
    resp = await client.get(f"/api/foods/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "FOOD_NOT_FOUND"
