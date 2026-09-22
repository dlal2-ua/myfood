"""Invitaciones (`domain/invites.py` + registro).

La app está publicada en internet: lo que se comprueba aquí es que sin código no se entra,
que un código sirve UNA vez, y que revocarlo lo inutiliza antes de que alguien lo use.
"""

import asyncio
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from myfood.app_settings import AppSettings
from myfood.db.session import AdminSessionLocal
from myfood.domain import invites
from myfood.main import app

pytestmark = pytest.mark.asyncio


@pytest.fixture
def invite_only(monkeypatch):
    """Instancia cerrada, sin tocar el fichero de ajustes real."""
    settings = AppSettings(invite_only=True, ai_enabled_by_default=False)
    monkeypatch.setattr("myfood.routers.auth.load_app_settings", lambda: settings)
    return settings


@pytest.fixture
def open_signup(monkeypatch):
    settings = AppSettings(invite_only=False, ai_enabled_by_default=True)
    monkeypatch.setattr("myfood.routers.auth.load_app_settings", lambda: settings)
    return settings


async def _new_code(superuser_conn, admin_id=None) -> str:
    code = invites.generate_code()
    await superuser_conn.execute(
        text("INSERT INTO invites (code, created_by) VALUES (:c, :a)"),
        {"c": code, "a": str(admin_id) if admin_id else None},
    )
    await superuser_conn.commit()
    return code


def client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="https://test")


async def _register(c: AsyncClient, code: str | None = None, **over):
    payload = {
        "email": f"inv-{uuid.uuid4()}@test.myfood",
        "password": "correcthorse123",
        "display_name": "Invitado",
        **over,
    }
    if code is not None:
        payload["invite_code"] = code
    return await c.post("/api/auth/register", json=payload), payload["email"]


async def _cleanup(superuser_conn, *emails):
    await superuser_conn.execute(
        text("DELETE FROM users WHERE email = ANY(:e)"), {"e": list(emails)}
    )
    await superuser_conn.commit()


def test_generated_codes_avoid_letters_that_look_alike():
    """Se dictan por teléfono y se escriben a mano: sin O/0 ni I/L/1 no hay confusión."""
    for _ in range(50):
        code = invites.generate_code()
        assert not set(code) & set("OIL01")
        assert len(code) == invites.CODE_LENGTH + 1  # con el guion


def test_a_code_is_accepted_however_it_is_typed():
    code = invites.generate_code()
    assert invites.normalize_code(code.lower()) == code
    assert invites.normalize_code(code.replace("-", "")) == code
    assert invites.normalize_code(f"  {code.lower()} ") == code


async def test_registering_without_a_code_is_refused(invite_only, superuser_conn):
    async with client() as c:
        resp, email = await _register(c)
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "INVITE_REQUIRED"
    left = await superuser_conn.scalar(
        text("SELECT count(*) FROM users WHERE email = :e"), {"e": email}
    )
    assert left == 0


async def test_an_invented_code_is_refused(invite_only):
    async with client() as c:
        resp, _ = await _register(c, code="ZZZZZ-ZZZZZ")
        assert resp.status_code == 403


async def test_a_valid_code_lets_one_person_in_and_then_is_burnt(invite_only, superuser_conn):
    code = await _new_code(superuser_conn)
    async with client() as c:
        first, email = await _register(c, code=code)
        assert first.status_code == 201
    async with client() as c:
        second, _ = await _register(c, code=code)
        assert second.status_code == 403

    row = (
        await superuser_conn.execute(
            text("SELECT used_by, used_at FROM invites WHERE code = :c"), {"c": code}
        )
    ).one()
    assert row.used_by is not None
    assert row.used_at is not None
    await _cleanup(superuser_conn, email)


async def test_the_code_is_accepted_lowercase_and_without_the_dash(invite_only, superuser_conn):
    code = await _new_code(superuser_conn)
    async with client() as c:
        resp, email = await _register(c, code=code.replace("-", "").lower())
        assert resp.status_code == 201
    await _cleanup(superuser_conn, email)


async def test_a_revoked_code_no_longer_works(invite_only, superuser_conn):
    code = await _new_code(superuser_conn)
    async with AdminSessionLocal() as session:
        assert await invites.revoke(session, code) is True
        await session.commit()
    async with client() as c:
        resp, _ = await _register(c, code=code)
        assert resp.status_code == 403


async def test_a_used_code_cannot_be_revoked(invite_only, superuser_conn):
    """Revocar uno ya usado borraría de dónde vino una cuenta que ya existe."""
    code = await _new_code(superuser_conn)
    async with client() as c:
        resp, email = await _register(c, code=code)
        assert resp.status_code == 201
    async with AdminSessionLocal() as session:
        assert await invites.revoke(session, code) is False
    await _cleanup(superuser_conn, email)


async def test_two_registrations_at_once_cannot_share_a_code(invite_only, superuser_conn):
    """El código se reclama con un UPDATE condicional: comprobar y escribir por separado
    dejaría entrar a los dos."""
    code = await _new_code(superuser_conn)
    emails = [f"race-{uuid.uuid4()}@test.myfood" for _ in range(4)]

    async def attempt(email: str):
        async with client() as c:
            resp, _ = await _register(c, code=code, email=email)
            return resp.status_code

    statuses = await asyncio.gather(*(attempt(e) for e in emails))
    assert statuses.count(201) == 1
    assert statuses.count(403) == 3

    created = await superuser_conn.scalar(
        text("SELECT count(*) FROM users WHERE email = ANY(:e)"), {"e": emails}
    )
    assert created == 1
    await _cleanup(superuser_conn, *emails)


async def test_with_signup_open_no_code_is_needed(open_signup, superuser_conn):
    async with client() as c:
        resp, email = await _register(c)
        assert resp.status_code == 201
    await _cleanup(superuser_conn, email)


async def test_new_accounts_follow_the_default_ai_setting(invite_only, superuser_conn):
    """El administrador decide si las cuentas nuevas pueden gastar cuota de Claude."""
    code = await _new_code(superuser_conn)
    async with client() as c:
        resp, email = await _register(c, code=code)
        assert resp.status_code == 201
    enabled = await superuser_conn.scalar(
        text("SELECT ai_enabled FROM users WHERE email = :e"), {"e": email}
    )
    assert enabled is False
    await _cleanup(superuser_conn, email)


async def test_the_public_config_says_whether_a_code_is_needed(invite_only, monkeypatch):
    async with client() as c:
        assert (await c.get("/api/auth/config")).json()["invite_only"] is True
