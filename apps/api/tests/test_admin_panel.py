"""Panel de administración: invitaciones, usuarios y resumen de la instancia.

Estas rutas ven datos de TODOS los usuarios (rol `myfood_admin`, sin RLS), así que además de
que funcionen se comprueba lo que NO deben devolver: nada del contenido de nadie.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from myfood.config import get_settings
from myfood.main import app

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _config_tmp_path(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "iafood_config_path", str(tmp_path / "iafood.json"))


@pytest_asyncio.fixture
async def admin_client(registered_client, superuser_conn):
    client, user_id = registered_client
    await superuser_conn.execute(
        text("UPDATE users SET role = 'admin' WHERE id = :id"), {"id": str(user_id)}
    )
    await superuser_conn.commit()
    yield client, user_id


async def test_only_an_admin_gets_in(registered_client):
    client, _ = registered_client
    for path in ["/api/admin/users", "/api/admin/invites", "/api/admin/overview"]:
        assert (await client.get(path)).status_code == 403


async def test_without_a_session_there_is_nothing(registered_client):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        assert (await c.get("/api/admin/users")).status_code == 401


async def test_an_admin_creates_a_code_and_sees_it_listed(admin_client):
    client, _ = admin_client
    created = await client.post("/api/admin/invites", json={"note": "Para Jorge"})
    assert created.status_code == 201
    code = created.json()["code"]
    assert created.json()["status"] == "disponible"
    assert created.json()["note"] == "Para Jorge"

    listed = (await client.get("/api/admin/invites")).json()
    assert any(i["code"] == code and i["status"] == "disponible" for i in listed)


async def test_revoking_a_code_shows_it_as_revoked(admin_client):
    client, _ = admin_client
    code = (await client.post("/api/admin/invites", json={})).json()["code"]
    assert (await client.delete(f"/api/admin/invites/{code}")).status_code == 204

    listed = (await client.get("/api/admin/invites")).json()
    assert next(i for i in listed if i["code"] == code)["status"] == "revocado"

    # Revocar dos veces no es un éxito silencioso: ya no hay nada que revocar.
    assert (await client.delete(f"/api/admin/invites/{code}")).status_code == 404


async def test_a_used_code_shows_who_used_it(admin_client, superuser_conn, monkeypatch):
    """Con la instancia cerrada, que es como sale en producción: el alta quema el código."""
    from myfood.app_settings import AppSettings

    client, _ = admin_client
    code = (await client.post("/api/admin/invites", json={})).json()["code"]
    monkeypatch.setattr(
        "myfood.routers.auth.load_app_settings",
        lambda: AppSettings(invite_only=True, ai_enabled_by_default=False),
    )
    email = f"inv-{uuid.uuid4()}@test.myfood"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        resp = await c.post(
            "/api/auth/register",
            json={
                "email": email,
                "password": "correcthorse123",
                "display_name": "Jorge",
                "invite_code": code,
            },
        )
    assert resp.status_code == 201

    listed = (await client.get("/api/admin/invites")).json()
    row = next(i for i in listed if i["code"] == code)
    assert row["status"] == "usado"
    assert row["used_by_name"] == "Jorge"

    await superuser_conn.execute(text("DELETE FROM users WHERE email = :e"), {"e": email})
    await superuser_conn.commit()


async def test_the_user_list_shows_activity_but_not_what_anyone_ate(admin_client, test_food):
    client, user_id = admin_client
    from datetime import date

    await client.post(
        "/api/log/food",
        json={
            "log_date": date.today().isoformat(),
            "meal_type": "lunch",
            "food_id": str(test_food),
            "grams": 100,
        },
    )
    users = (await client.get("/api/admin/users")).json()
    me = next(u for u in users if u["id"] == str(user_id))
    assert me["logging_days"] == 1
    assert me["last_log_date"] == date.today().isoformat()
    assert me["role"] == "admin"
    # Recuentos y fechas, nunca el contenido: ni alimentos, ni calorías, ni medidas.
    assert not any(
        key in me for key in ("foods", "entries", "kcal", "weight_kg", "measurements")
    )


async def test_the_admin_switches_the_ai_off_for_someone(admin_client, superuser_conn):
    client, _ = admin_client
    other = uuid.uuid4()
    await superuser_conn.execute(
        text(
            "INSERT INTO users (id, email, password_hash, display_name) "
            "VALUES (:id, :email, 'x', 'Otra')"
        ),
        {"id": str(other), "email": f"other-{other}@test.myfood"},
    )
    await superuser_conn.commit()

    patched = await client.patch(f"/api/admin/users/{other}", json={"ai_enabled": False})
    assert patched.status_code == 200
    assert patched.json()["ai_enabled"] is False

    stored = await superuser_conn.scalar(
        text("SELECT ai_enabled FROM users WHERE id = :id"), {"id": str(other)}
    )
    assert stored is False

    await superuser_conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": str(other)})
    await superuser_conn.commit()


async def test_an_admin_cannot_lock_themselves_out(admin_client):
    """Desactivarse a uno mismo deja la instancia sin nadie que pueda administrarla."""
    client, user_id = admin_client
    resp = await client.patch(f"/api/admin/users/{user_id}", json={"is_active": False})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "CANNOT_DISABLE_SELF"


async def test_a_disabled_user_cannot_log_in(admin_client, superuser_conn):
    client, _ = admin_client
    email = f"off-{uuid.uuid4()}@test.myfood"
    other = uuid.uuid4()
    from myfood.security import hash_password

    await superuser_conn.execute(
        text(
            "INSERT INTO users (id, email, password_hash, display_name) "
            "VALUES (:id, :email, :h, 'Apagada')"
        ),
        {"id": str(other), "email": email, "h": hash_password("correcthorse123")},
    )
    await superuser_conn.commit()

    await client.patch(f"/api/admin/users/{other}", json={"is_active": False})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as c:
        resp = await c.post(
            "/api/auth/login", json={"email": email, "password": "correcthorse123"}
        )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "ACCOUNT_DISABLED"

    await superuser_conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": str(other)})
    await superuser_conn.commit()


async def test_the_ai_is_refused_to_a_user_the_admin_turned_off(admin_client, superuser_conn):
    client, user_id = admin_client
    await client.post("/api/consents", json={"kind": "ai_processing", "version": "v1"})
    await superuser_conn.execute(
        text("UPDATE users SET ai_enabled = false WHERE id = :id"), {"id": str(user_id)}
    )
    await superuser_conn.commit()

    resp = await client.post("/api/log/smart", json={"text": "dos huevos"})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "AI_DISABLED_FOR_USER"


async def test_the_overview_counts_without_leaking(admin_client):
    client, _ = admin_client
    body = (await client.get("/api/admin/overview")).json()
    assert body["users_total"] >= 1
    assert body["users_active"] >= 1
    assert isinstance(body["top_foods_7d"], list)
    assert body["ai_instance_limit"] > 0
    assert body["database_size"]


async def test_the_activity_series_covers_every_day_asked_for(admin_client):
    client, _ = admin_client
    body = (await client.get("/api/admin/activity?days=14")).json()
    assert len(body) == 14
    assert all("entries" in d and "users" in d for d in body)
    # Días sin nada también salen, o la gráfica mentiría sobre los huecos.
    assert all(d["entries"] >= 0 for d in body)


async def test_the_settings_can_be_changed_without_restarting(admin_client):
    client, _ = admin_client
    await client.put(
        "/api/admin/settings", json={"invite_only": False, "ai_enabled_by_default": True}
    )
    assert (await client.get("/api/admin/settings")).json() == {
        "invite_only": False,
        "ai_enabled_by_default": True,
    }
    assert (await client.get("/api/auth/config")).json()["invite_only"] is False
