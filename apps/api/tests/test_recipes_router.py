"""Recetas propias (sección 6.4/20). Los totales nutricionales se calculan
en cada lectura sumando `food_nutrients` de cada ingrediente (R9 — nunca un
valor guardado), igual criterio ya probado para `/log` en `test_log.py`.

`POST /recipes/import-url` en sí (descarga + `recipe_scrapers` + agente) se
prueba en `test_recipe_import_flow.py` — aquí solo se ejercita el cableado
del endpoint (consentimiento, cuotas, credencial), mismo patrón que
`test_log_smart_router.py` para `/log/smart`."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from myfood.ai import client as ai_client
from myfood.ai.queue import RECIPE_IMPORT_QUEUE_KEY
from myfood.ai.queue import _redis as queue_redis
from myfood.config import get_settings
from myfood.db.session import AdminSessionLocal

pytestmark = pytest.mark.asyncio


async def test_create_recipe_computes_totals_from_ingredients(registered_client, test_food):
    client, _ = registered_client
    resp = await client.post(
        "/api/recipes",
        json={
            "name": "Pollo con arroz",
            "servings": 2,
            "prep_minutes": 20,
            "ingredients": [{"food_id": str(test_food), "grams": 200}],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Pollo con arroz"
    assert body["servings"] == 2
    assert len(body["ingredients"]) == 1
    assert body["ingredients"][0]["kcal"] == 330.0  # 165 * 2
    assert body["totals"]["kcal"] == 330.0
    assert body["totals_per_serving"]["kcal"] == 165.0


async def test_create_recipe_without_ingredients(registered_client):
    client, _ = registered_client
    resp = await client.post("/api/recipes", json={"name": "Receta vacía"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["ingredients"] == []
    assert body["totals"] == {"kcal": 0, "protein_g": 0, "fat_g": 0, "carbs_g": 0}


async def test_list_recipes_returns_only_own_recipes(registered_client, test_food):
    client, _ = registered_client
    await client.post("/api/recipes", json={"name": "Receta A"})
    await client.post("/api/recipes", json={"name": "Receta B"})

    resp = await client.get("/api/recipes")
    assert resp.status_code == 200
    names = {r["name"] for r in resp.json()}
    assert names == {"Receta A", "Receta B"}


async def test_get_recipe_not_found(registered_client):
    resp = await registered_client[0].get(f"/api/recipes/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "RECIPE_NOT_FOUND"


async def test_patch_recipe_updates_fields(registered_client):
    client, _ = registered_client
    created = await client.post("/api/recipes", json={"name": "Original", "servings": 1})
    recipe_id = created.json()["id"]

    resp = await client.patch(
        f"/api/recipes/{recipe_id}", json={"name": "Renombrada", "servings": 4}
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renombrada"
    assert resp.json()["servings"] == 4


async def test_delete_recipe_cascades_ingredients(registered_client, test_food):
    client, _ = registered_client
    created = await client.post(
        "/api/recipes",
        json={"name": "A borrar", "ingredients": [{"food_id": str(test_food), "grams": 50}]},
    )
    recipe_id = created.json()["id"]

    resp = await client.delete(f"/api/recipes/{recipe_id}")
    assert resp.status_code == 204

    get_resp = await client.get(f"/api/recipes/{recipe_id}")
    assert get_resp.status_code == 404


async def test_add_update_remove_ingredient(registered_client, test_food):
    client, _ = registered_client
    created = await client.post("/api/recipes", json={"name": "Con ingredientes"})
    recipe_id = created.json()["id"]

    add_resp = await client.post(
        f"/api/recipes/{recipe_id}/ingredients",
        json={"food_id": str(test_food), "grams": 100},
    )
    assert add_resp.status_code == 201
    ingredient_id = add_resp.json()["ingredients"][0]["id"]
    assert add_resp.json()["totals"]["kcal"] == 165.0

    update_resp = await client.patch(
        f"/api/recipes/{recipe_id}/ingredients/{ingredient_id}",
        json={"food_id": str(test_food), "grams": 50},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["totals"]["kcal"] == 82.5

    remove_resp = await client.delete(f"/api/recipes/{recipe_id}/ingredients/{ingredient_id}")
    assert remove_resp.status_code == 204

    final = await client.get(f"/api/recipes/{recipe_id}")
    assert final.json()["ingredients"] == []


async def test_another_users_recipe_is_404(registered_client, superuser_conn):
    """R3 — ningún endpoint devuelve ni modifica recetas de otro usuario."""
    from httpx import ASGITransport, AsyncClient

    from myfood.main import app

    client, _ = registered_client
    created = await client.post("/api/recipes", json={"name": "Privada"})
    recipe_id = created.json()["id"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as other_client:
        email = f"other-{uuid.uuid4()}@test.myfood"
        other_resp = await other_client.post(
            "/api/auth/register",
            json={"email": email, "password": "correcthorse123", "display_name": "Other"},
        )
        other_id = other_resp.json()["id"]

        get_resp = await other_client.get(f"/api/recipes/{recipe_id}")
        assert get_resp.status_code == 404
        patch_resp = await other_client.patch(f"/api/recipes/{recipe_id}", json={"name": "hack"})
        assert patch_resp.status_code == 404
        delete_resp = await other_client.delete(f"/api/recipes/{recipe_id}")
        assert delete_resp.status_code == 404

    await superuser_conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": other_id})
    await superuser_conn.commit()


# --- POST /recipes/import-url (solo el cableado del endpoint) --------------


@pytest_asyncio.fixture(autouse=True)
async def _iafood_config_tmp_path(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "iafood_config_path", str(tmp_path / "iafood.json"))


@pytest_asyncio.fixture(autouse=True)
async def _clean_ai_credential_and_queue(registered_client):
    yield
    async with AdminSessionLocal() as session:
        await session.execute(text("DELETE FROM ai_credentials"))
        await session.commit()
    await queue_redis.delete(RECIPE_IMPORT_QUEUE_KEY)


async def test_recipe_import_requires_consent(registered_client):
    client, user_id = registered_client
    async with AdminSessionLocal() as session:
        await ai_client.set_credential(session, admin_user_id=user_id, token="fake-token")
        await session.commit()

    resp = await client.post("/api/recipes/import-url", json={"url": "http://8.8.8.8/recipe"})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "AI_CONSENT_REQUIRED"


async def test_recipe_import_requires_credential(registered_client):
    client, _ = registered_client
    await client.post("/api/consents", json={"kind": "ai_processing", "version": "v1"})

    resp = await client.post("/api/recipes/import-url", json={"url": "http://8.8.8.8/recipe"})
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "AI_NOT_CONFIGURED"


async def test_recipe_import_rejects_unsafe_url(registered_client):
    client, user_id = registered_client
    async with AdminSessionLocal() as session:
        await ai_client.set_credential(session, admin_user_id=user_id, token="fake-token")
        await session.commit()
    await client.post("/api/consents", json={"kind": "ai_processing", "version": "v1"})

    resp = await client.post(
        "/api/recipes/import-url", json={"url": "http://169.254.169.254/latest/meta-data/"}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "UNSAFE_URL"


async def test_recipe_import_succeeds_and_can_be_polled(registered_client):
    client, user_id = registered_client
    async with AdminSessionLocal() as session:
        await ai_client.set_credential(session, admin_user_id=user_id, token="fake-token")
        await session.commit()
    await client.post("/api/consents", json={"kind": "ai_processing", "version": "v1"})

    resp = await client.post("/api/recipes/import-url", json={"url": "http://8.8.8.8/recipe"})
    assert resp.status_code == 202
    body = resp.json()
    assert body["kind"] == "recipe_import"
    assert body["status"] == "running"

    status_resp = await client.get(f"/api/ai/sessions/{body['id']}")
    assert status_resp.status_code == 200
    assert status_resp.json()["id"] == body["id"]
