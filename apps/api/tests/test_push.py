"""Tests de suscripción Web Push (sección 10, Fase 3) — nunca se envía una
notificación real desde estos tests, solo se guarda/borra la suscripción."""


async def test_vapid_public_key_is_exposed(registered_client):
    client, _user_id = registered_client
    resp = await client.get("/api/push/vapid-public-key")
    assert resp.status_code == 200
    assert "public_key" in resp.json()


async def test_subscribe_and_unsubscribe(registered_client):
    client, _user_id = registered_client
    payload = {
        "endpoint": "https://push.example.com/abc123",
        "keys": {"p256dh": "fake-p256dh", "auth": "fake-auth"},
        "device": "test-browser",
    }
    resp = await client.post("/api/push/subscribe", json=payload)
    assert resp.status_code == 201
    assert "id" in resp.json()

    resp2 = await client.post("/api/push/unsubscribe", json={"endpoint": payload["endpoint"]})
    assert resp2.status_code == 204


async def test_resubscribing_same_endpoint_updates_in_place(registered_client):
    client, _user_id = registered_client
    endpoint = "https://push.example.com/resub"
    first = await client.post(
        "/api/push/subscribe",
        json={"endpoint": endpoint, "keys": {"p256dh": "a", "auth": "a"}},
    )
    second = await client.post(
        "/api/push/subscribe",
        json={"endpoint": endpoint, "keys": {"p256dh": "b", "auth": "b"}},
    )
    assert first.json()["id"] == second.json()["id"]

    await client.post("/api/push/unsubscribe", json={"endpoint": endpoint})


async def test_unauthenticated_subscribe_rejected():
    import uuid

    from httpx import ASGITransport, AsyncClient

    from myfood.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        resp = await client.post(
            "/api/push/subscribe",
            json={
                "endpoint": f"https://push.example.com/{uuid.uuid4()}",
                "keys": {"p256dh": "a", "auth": "a"},
            },
        )
    assert resp.status_code == 401
