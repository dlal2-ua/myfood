"""2FA por TOTP (Fase 7, documento 2 sección 17 — "2FA/passkeys funcionan
para iniciar sesión"). `pyotp` genera los códigos en los propios tests, tal
y como lo haría una app autenticadora real (Google Authenticator, Aegis...)
apuntando al mismo secreto."""

import pyotp
import pytest

pytestmark = pytest.mark.asyncio

_PASSWORD = "correcthorse123"  # ver conftest.py::registered_client


async def _enable_totp(client) -> str:
    setup = await client.post("/api/auth/2fa/setup")
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    totp = pyotp.TOTP(secret)
    confirm = await client.post("/api/auth/2fa/confirm", json={"code": totp.now()})
    assert confirm.status_code == 200
    assert confirm.json()["totp_enabled"] is True
    return secret


async def test_setup_returns_secret_and_valid_otpauth_uri(registered_client):
    client, _ = registered_client
    resp = await client.post("/api/auth/2fa/setup")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["secret"]) >= 16
    assert body["otpauth_uri"].startswith("otpauth://totp/")
    assert "MyFood" in body["otpauth_uri"]


async def test_confirm_with_wrong_code_is_401_and_stays_disabled(registered_client):
    client, _ = registered_client
    await client.post("/api/auth/2fa/setup")

    resp = await client.post("/api/auth/2fa/confirm", json={"code": "000000"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_TOTP_CODE"

    me = await client.get("/api/auth/me")
    assert me.json()["totp_enabled"] is False


async def test_confirm_with_real_code_enables_2fa(registered_client):
    client, _ = registered_client
    await _enable_totp(client)

    me = await client.get("/api/auth/me")
    assert me.json()["totp_enabled"] is True


async def test_login_with_2fa_enabled_requires_second_step(registered_client):
    client, user_id = registered_client
    email = (await client.get("/api/auth/me")).json()["email"]
    secret = await _enable_totp(client)

    # Un cliente nuevo, como si fuera otro dispositivo iniciando sesión.
    from httpx import ASGITransport, AsyncClient

    from myfood.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as fresh_client:
        login = await fresh_client.post(
            "/api/auth/login", json={"email": email, "password": _PASSWORD}
        )
        assert login.status_code == 200
        body = login.json()
        assert body["mfa_required"] is True
        assert "id" not in body  # todavía no hay sesión completa

        # Sin el mfa_token todavía no hay cookie de sesión real.
        me_before = await fresh_client.get("/api/auth/me")
        assert me_before.status_code == 401

        verify = await fresh_client.post(
            "/api/auth/2fa/verify-login",
            json={"mfa_token": body["mfa_token"], "code": pyotp.TOTP(secret).now()},
        )
        assert verify.status_code == 200
        assert verify.json()["id"] == str(user_id)

        me_after = await fresh_client.get("/api/auth/me")
        assert me_after.status_code == 200


async def test_verify_login_with_wrong_code_is_401(registered_client):
    client, _ = registered_client
    email = (await client.get("/api/auth/me")).json()["email"]
    await _enable_totp(client)

    from httpx import ASGITransport, AsyncClient

    from myfood.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as fresh_client:
        login = await fresh_client.post(
            "/api/auth/login", json={"email": email, "password": _PASSWORD}
        )
        mfa_token = login.json()["mfa_token"]

        resp = await fresh_client.post(
            "/api/auth/2fa/verify-login", json={"mfa_token": mfa_token, "code": "000000"}
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "INVALID_TOTP_CODE"


async def test_verify_login_with_unknown_mfa_token_is_401(registered_client):
    client, _ = registered_client
    resp = await client.post(
        "/api/auth/2fa/verify-login", json={"mfa_token": "no-existe", "code": "123456"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "MFA_CHALLENGE_EXPIRED"


async def test_mfa_token_is_single_use(registered_client):
    client, _ = registered_client
    email = (await client.get("/api/auth/me")).json()["email"]
    secret = await _enable_totp(client)

    from httpx import ASGITransport, AsyncClient

    from myfood.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as fresh_client:
        login = await fresh_client.post(
            "/api/auth/login", json={"email": email, "password": _PASSWORD}
        )
        mfa_token = login.json()["mfa_token"]
        code = pyotp.TOTP(secret).now()

        first = await fresh_client.post(
            "/api/auth/2fa/verify-login", json={"mfa_token": mfa_token, "code": code}
        )
        assert first.status_code == 200

        second = await fresh_client.post(
            "/api/auth/2fa/verify-login", json={"mfa_token": mfa_token, "code": code}
        )
        assert second.status_code == 401
        assert second.json()["error"]["code"] == "MFA_CHALLENGE_EXPIRED"


async def test_disable_requires_correct_password(registered_client):
    client, _ = registered_client
    await _enable_totp(client)

    wrong = await client.post("/api/auth/2fa/disable", json={"password": "mala"})
    assert wrong.status_code == 401
    assert (await client.get("/api/auth/me")).json()["totp_enabled"] is True

    right = await client.post("/api/auth/2fa/disable", json={"password": _PASSWORD})
    assert right.status_code == 200
    assert right.json()["totp_enabled"] is False
    assert (await client.get("/api/auth/me")).json()["totp_enabled"] is False


async def test_login_without_2fa_still_works_as_before(registered_client):
    """No romper el flujo normal para cuentas sin 2FA activado."""
    client, _ = registered_client
    email = (await client.get("/api/auth/me")).json()["email"]

    from httpx import ASGITransport, AsyncClient

    from myfood.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as fresh_client:
        login = await fresh_client.post(
            "/api/auth/login", json={"email": email, "password": _PASSWORD}
        )
        assert login.status_code == 200
        body = login.json()
        assert "mfa_required" not in body
        assert body["email"] == email
