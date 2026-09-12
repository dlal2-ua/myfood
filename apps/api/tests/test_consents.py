async def test_grant_consent_appears_in_auth_me(registered_client):
    client, _ = registered_client

    resp = await client.post("/api/consents", json={"kind": "ai_processing", "version": "v1"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["kind"] == "ai_processing"
    assert body["version"] == "v1"
    assert body["granted_at"]

    me = await client.get("/api/auth/me")
    assert "ai_processing" in me.json()["granted_consents"]


async def test_granting_twice_is_idempotent_not_duplicated(registered_client):
    client, _ = registered_client

    await client.post("/api/consents", json={"kind": "ai_processing", "version": "v1"})
    resp = await client.post("/api/consents", json={"kind": "ai_processing", "version": "v2"})
    assert resp.status_code == 201
    assert resp.json()["version"] == "v2"

    me = await client.get("/api/auth/me")
    assert me.json()["granted_consents"].count("ai_processing") == 1


async def test_grant_requires_authentication():
    from httpx import ASGITransport, AsyncClient

    from myfood.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        resp = await client.post("/api/consents", json={"kind": "ai_processing", "version": "v1"})
    assert resp.status_code == 401


async def test_grant_rejects_blank_kind(registered_client):
    client, _ = registered_client
    resp = await client.post("/api/consents", json={"kind": "", "version": "v1"})
    assert resp.status_code == 422
