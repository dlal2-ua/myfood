"""Límite de intentos fallidos (`ratelimit.py`): login, TOTP y confirmaciones con
contraseña. Cada test usa emails/usuarios propios y una IP simulada propia (cabecera
`CF-Connecting-IP`, la que fija Cloudflare) para que sus contadores no se pisen."""

import uuid

import pyotp
import pytest
from httpx import ASGITransport, AsyncClient

from myfood.main import app

pytestmark = pytest.mark.asyncio

PASSWORD = "correcthorse123"


def _ip() -> str:
    n = uuid.uuid4().int
    return f"10.{n % 250}.{(n >> 8) % 250}.{(n >> 16) % 250}"


@pytest.fixture
async def http():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        yield client


async def _register(http, superuser_conn, *, ip: str | None = None):
    from sqlalchemy import text

    email = f"rl-{uuid.uuid4()}@test.myfood"
    resp = await http.post(
        "/api/auth/register",
        json={"email": email, "password": PASSWORD, "display_name": "RL"},
        headers={"CF-Connecting-IP": ip or _ip()},
    )
    assert resp.status_code == 201
    user_id = resp.json()["id"]
    http.cookies.clear()
    return email, user_id, superuser_conn, text


async def _login(http, email, password, ip):
    return await http.post(
        "/api/auth/login",
        json={"email": email, "password": password},
        headers={"CF-Connecting-IP": ip},
    )


async def _cleanup(superuser_conn, text, user_id):
    await superuser_conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
    await superuser_conn.commit()


async def test_five_wrong_passwords_lock_the_pair_even_for_the_right_password(
    http, superuser_conn
):
    email, user_id, conn, text = await _register(http, superuser_conn)
    ip = _ip()
    try:
        for _ in range(5):
            assert (await _login(http, email, "mal-mal-mal", ip)).status_code == 401
        blocked = await _login(http, email, PASSWORD, ip)  # incluso con la buena
        assert blocked.status_code == 429
        body = blocked.json()["error"]
        assert body["code"] == "AUTH_RATE_LIMITED"
        assert body["details"]["retry_after_seconds"] > 0
    finally:
        await _cleanup(conn, text, user_id)


async def test_the_lock_does_not_leak_to_other_accounts_from_the_same_ip(http, superuser_conn):
    victim, victim_id, conn, text = await _register(http, superuser_conn)
    other, other_id, _, _ = await _register(http, superuser_conn)
    ip = _ip()
    try:
        for _ in range(5):
            await _login(http, victim, "mal-mal-mal", ip)
        assert (await _login(http, victim, PASSWORD, ip)).status_code == 429
        assert (await _login(http, other, PASSWORD, ip)).status_code == 200
    finally:
        await _cleanup(conn, text, victim_id)
        await _cleanup(conn, text, other_id)


async def test_a_successful_login_resets_the_pair_counter(http, superuser_conn):
    email, user_id, conn, text = await _register(http, superuser_conn)
    ip = _ip()
    try:
        for _ in range(4):
            assert (await _login(http, email, "mal-mal-mal", ip)).status_code == 401
        assert (await _login(http, email, PASSWORD, ip)).status_code == 200
        for _ in range(4):  # otros 4 fallos: sin el reinicio ya habrían bloqueado
            assert (await _login(http, email, "mal-mal-mal", ip)).status_code == 401
    finally:
        await _cleanup(conn, text, user_id)


async def test_someone_elses_failures_from_another_ip_do_not_lock_the_real_owner_out(
    http, superuser_conn
):
    email, user_id, conn, text = await _register(http, superuser_conn)
    try:
        attacker_ip = _ip()
        for _ in range(5):
            await _login(http, email, "mal-mal-mal", attacker_ip)
        assert (await _login(http, email, PASSWORD, attacker_ip)).status_code == 429
        assert (await _login(http, email, PASSWORD, _ip())).status_code == 200
    finally:
        await _cleanup(conn, text, user_id)


async def test_a_distributed_attack_on_one_account_locks_it_for_every_ip(http, superuser_conn):
    email, user_id, conn, text = await _register(http, superuser_conn)
    try:
        for _ in range(20):  # 20 IPs distintas, 1 fallo cada una: ninguna par se bloquea
            assert (await _login(http, email, "mal-mal-mal", _ip())).status_code == 401
        assert (await _login(http, email, PASSWORD, _ip())).status_code == 429
    finally:
        await _cleanup(conn, text, user_id)


async def test_spraying_many_accounts_from_one_ip_locks_that_ip(http):
    ip = _ip()
    for i in range(30):
        resp = await _login(http, f"nadie-{i}-{uuid.uuid4()}@test.myfood", "mal-mal-mal", ip)
        assert resp.status_code == 401
    last = await _login(http, f"otro-{uuid.uuid4()}@test.myfood", "x-x-x-x-x-x", ip)
    assert last.status_code == 429


async def test_unknown_and_known_emails_are_limited_the_same_way(http, superuser_conn):
    """No debe delatar qué emails existen: el 429 llega igual a los 5 fallos."""
    ip = _ip()
    ghost = f"fantasma-{uuid.uuid4()}@test.myfood"
    for _ in range(5):
        assert (await _login(http, ghost, "mal-mal-mal", ip)).status_code == 401
    assert (await _login(http, ghost, "mal-mal-mal", ip)).status_code == 429


async def _enable_2fa(client) -> str:
    setup = await client.post("/api/auth/2fa/setup")
    secret = setup.json()["secret"]
    confirm = await client.post("/api/auth/2fa/confirm", json={"code": pyotp.TOTP(secret).now()})
    assert confirm.status_code == 200
    return secret


async def test_totp_guessing_is_limited_and_a_right_code_still_works_before_the_limit(
    registered_client, http
):
    client, user_id = registered_client
    email = (await client.get("/api/auth/me")).json()["email"]
    secret = await _enable_2fa(client)
    ip = _ip()

    first = await _login(http, email, PASSWORD, ip)
    assert first.json()["mfa_required"] is True
    token = first.json()["mfa_token"]
    for _ in range(4):
        wrong = await http.post(
            "/api/auth/2fa/verify-login", json={"mfa_token": token, "code": "000000"}
        )
        assert wrong.status_code == 401
    ok = await http.post(
        "/api/auth/2fa/verify-login", json={"mfa_token": token, "code": pyotp.TOTP(secret).now()}
    )
    assert ok.status_code == 200

    # Y tras 5 fallos seguidos ya no se acepta ni el código bueno.
    second = await _login(http, email, PASSWORD, _ip())
    token2 = second.json()["mfa_token"]
    for _ in range(5):
        await http.post("/api/auth/2fa/verify-login", json={"mfa_token": token2, "code": "000000"})
    blocked = await http.post(
        "/api/auth/2fa/verify-login",
        json={"mfa_token": token2, "code": pyotp.TOTP(secret).now()},
    )
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "AUTH_RATE_LIMITED"


async def test_delete_account_password_guessing_is_limited(registered_client):
    client, _user_id = registered_client
    for _ in range(5):
        resp = await client.post("/api/privacy/delete-account", json={"password": "mal-mal-mal"})
        assert resp.status_code == 401
    blocked = await client.post("/api/privacy/delete-account", json={"password": "correcthorse123"})
    assert blocked.status_code == 429
    assert (await client.get("/api/auth/me")).status_code == 200  # la cuenta sigue viva


async def test_disabling_2fa_password_guessing_is_limited(registered_client):
    client, _user_id = registered_client
    await _enable_2fa(client)
    for _ in range(5):
        resp = await client.post("/api/auth/2fa/disable", json={"password": "mal-mal-mal"})
        assert resp.status_code == 401
    blocked = await client.post("/api/auth/2fa/disable", json={"password": "correcthorse123"})
    assert blocked.status_code == 429


def test_client_ip_prefers_cloudflare_then_forwarded_for_then_socket():
    from starlette.requests import Request

    from myfood.ratelimit import client_ip

    def req(headers: dict[str, str], client=("9.9.9.9", 1)):
        raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
        return Request({"type": "http", "headers": raw, "client": client})

    both = req({"CF-Connecting-IP": "1.1.1.1", "X-Forwarded-For": "2.2.2.2"})
    assert client_ip(both) == "1.1.1.1"
    assert client_ip(req({"X-Forwarded-For": "2.2.2.2, 3.3.3.3"})) == "2.2.2.2"
    assert client_ip(req({})) == "9.9.9.9"
