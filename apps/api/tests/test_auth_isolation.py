"""R3 + R11 — aislamiento multiusuario.

El criterio de aceptación de la Fase 0 exige comprobar el aislamiento incluso
cuando, a propósito, se omite el filtro `WHERE user_id` de una consulta — es
decir, que la política RLS de Postgres (sección 22) sea la que realmente
impide la fuga de datos, no solo la disciplina del código de la aplicación.
"""

import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio


async def test_rls_blocks_query_without_user_id_filter(app_engine, two_users):
    user_a, user_b = two_users

    async with app_engine.connect() as conn:
        # SET no admite bind params en Postgres; user_a es un uuid.UUID ya
        # validado, no texto de usuario (ver db/session.py:set_rls_context).
        await conn.execute(text(f"SET LOCAL app.current_user_id = '{user_a}'"))
        # Consulta deliberadamente SIN "WHERE user_id = ..." — simula el bug
        # que R11 debe cubrir aunque el filtrado en código falle.
        rows = (await conn.execute(text("SELECT user_id FROM profiles"))).all()

    seen = {str(r.user_id) for r in rows}
    assert str(user_a) in seen
    assert str(user_b) not in seen


async def test_rls_returns_nothing_without_context(app_engine, two_users):
    user_a, user_b = two_users

    async with app_engine.connect() as conn:
        # Sin SET LOCAL app.current_user_id: current_setting(..., true) es NULL,
        # y NULL = user_id nunca es verdadero -> ninguna fila visible.
        rows = (await conn.execute(text("SELECT user_id FROM profiles"))).all()

    seen = {str(r.user_id) for r in rows}
    assert str(user_a) not in seen
    assert str(user_b) not in seen


async def test_register_login_logout_flow():
    from httpx import ASGITransport, AsyncClient

    from myfood.main import app

    transport = ASGITransport(app=app)
    # base_url en https: la cookie de sesión lleva Secure (obligatorio en
    # producción, ver security.py); ASGITransport no valida TLS de verdad,
    # pero httpx sí exige el esquema https para aceptar cookies Secure.
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        email = f"flow-test-{uuid.uuid4()}@example.com"
        resp = await client.post(
            "/api/auth/register",
            json={"email": email, "password": "correcthorse123", "display_name": "Flujo Test"},
        )
        assert resp.status_code == 201
        assert client.cookies.get("myfood_session") is not None

        me = await client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["email"] == email

        logout = await client.post("/api/auth/logout")
        assert logout.status_code == 204

        me_after_logout = await client.get("/api/auth/me")
        assert me_after_logout.status_code == 401
