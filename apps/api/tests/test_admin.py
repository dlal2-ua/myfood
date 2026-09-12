import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from myfood.config import get_settings


@pytest_asyncio.fixture(autouse=True)
async def _iafood_config_tmp_path(tmp_path, monkeypatch):
    """Evita que estos tests toquen /data/config (solo existe dentro del
    contenedor), y aísla cada test de los demás y de un despliegue real."""
    monkeypatch.setattr(get_settings(), "iafood_config_path", str(tmp_path / "iafood.json"))


@pytest_asyncio.fixture(autouse=True)
async def _clean_ai_credential(superuser_conn, registered_client):
    # Depende explícitamente de `registered_client` para que pytest lo
    # desmonte ANTES (LIFO) de que ese fixture borre su usuario de prueba —
    # si no, `ai_credentials.updated_by` (FK a `users.id`) bloquea ese DELETE.
    await superuser_conn.execute(text("DELETE FROM ai_credentials"))
    await superuser_conn.commit()
    yield
    await superuser_conn.execute(text("DELETE FROM ai_credentials"))
    await superuser_conn.commit()


@pytest_asyncio.fixture
async def admin_client(registered_client, superuser_conn):
    client, user_id = registered_client
    await superuser_conn.execute(
        text("UPDATE users SET role = 'admin' WHERE id = :id"), {"id": str(user_id)}
    )
    await superuser_conn.commit()
    yield client, user_id


async def test_unauthenticated_request_is_401():
    from myfood.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        resp = await client.get("/api/admin/ai/credential")
    assert resp.status_code == 401


async def test_non_admin_user_is_403(registered_client):
    client, _ = registered_client
    resp = await client.get("/api/admin/ai/credential")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    resp2 = await client.get("/api/admin/ai/limits")
    assert resp2.status_code == 403


async def test_admin_credential_starts_unconfigured(admin_client):
    client, _ = admin_client
    resp = await client.get("/api/admin/ai/credential")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"configured": False, "provider": None, "updated_at": None}


async def test_admin_sets_credential_and_never_returns_it(admin_client):
    client, _ = admin_client
    resp = await client.put("/api/admin/ai/credential", json={"token": "sk-ant-oat-test"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["provider"] == "anthropic"
    assert body["updated_at"] is not None
    assert "token" not in body
    assert "sk-ant-oat-test" not in resp.text

    resp2 = await client.get("/api/admin/ai/credential")
    assert resp2.json()["configured"] is True


async def test_admin_rejects_blank_token(admin_client):
    client, _ = admin_client
    resp = await client.put("/api/admin/ai/credential", json={"token": "   "})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_TOKEN"


async def test_admin_limits_defaults(admin_client):
    client, _ = admin_client
    resp = await client.get("/api/admin/ai/limits")
    assert resp.status_code == 200
    assert resp.json() == {
        "per_profile_daily": 10,
        "instance_daily": 30,
        "max_tokens_per_call": 8000,
    }


async def test_admin_updates_limits_and_get_reflects_it(admin_client):
    client, _ = admin_client
    resp = await client.put(
        "/api/admin/ai/limits",
        json={"per_profile_daily": 3, "instance_daily": 15, "max_tokens_per_call": 4000},
    )
    assert resp.status_code == 200
    assert resp.json()["per_profile_daily"] == 3

    resp2 = await client.get("/api/admin/ai/limits")
    assert resp2.json() == {
        "per_profile_daily": 3,
        "instance_daily": 15,
        "max_tokens_per_call": 4000,
    }


async def test_admin_limits_rejects_out_of_range_values(admin_client):
    client, _ = admin_client
    resp = await client.put(
        "/api/admin/ai/limits",
        json={"per_profile_daily": 0, "instance_daily": 30, "max_tokens_per_call": 8000},
    )
    assert resp.status_code == 422
