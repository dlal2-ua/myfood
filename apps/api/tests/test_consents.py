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


# --- R4: consentimiento explícito de datos de salud ---------------------------------


async def test_a_new_user_has_the_health_data_consent_pending(fresh_client):
    client, _user_id = fresh_client
    me = (await client.get("/api/auth/me")).json()
    assert me["pending_consents"] == ["health_data"]
    assert "health_data" not in me["granted_consents"]


async def test_health_data_cannot_be_written_without_the_consent(fresh_client):
    client, _user_id = fresh_client
    profile = await client.put("/api/profile", json={"sex": "male", "height_cm": 180})
    assert profile.status_code == 403
    assert profile.json()["error"]["code"] == "HEALTH_DATA_CONSENT_REQUIRED"
    measurement = await client.post(
        "/api/measurements", json={"measured_on": "2026-01-10", "weight_kg": 80}
    )
    assert measurement.status_code == 403
    assert measurement.json()["error"]["code"] == "HEALTH_DATA_CONSENT_REQUIRED"


async def test_accepting_the_consent_unblocks_the_writes_and_clears_pending(fresh_client):
    client, _user_id = fresh_client
    granted = await client.post("/api/consents", json={"kind": "health_data", "version": "v1"})
    assert granted.status_code == 201
    assert (await client.get("/api/auth/me")).json()["pending_consents"] == []
    profile = await client.put("/api/profile", json={"sex": "male", "height_cm": 180})
    assert profile.status_code == 200


async def test_revoking_health_data_blocks_writes_again_and_reappears_as_pending(
    registered_client,
):
    client, _user_id = registered_client
    assert (await client.put("/api/profile", json={"height_cm": 175})).status_code == 200

    revoked = await client.delete("/api/consents/health_data")
    assert revoked.status_code == 204
    assert (await client.get("/api/auth/me")).json()["pending_consents"] == ["health_data"]
    blocked = await client.put("/api/profile", json={"height_cm": 176})
    assert blocked.status_code == 403

    # Volver a aceptar reactiva.
    await client.post("/api/consents", json={"kind": "health_data", "version": "v1"})
    assert (await client.put("/api/profile", json={"height_cm": 176})).status_code == 200


async def test_revoking_something_not_granted_is_404(fresh_client):
    client, _user_id = fresh_client
    resp = await client.delete("/api/consents/ai_processing")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "CONSENT_NOT_GRANTED"


async def test_list_consents_reports_status_and_which_are_required(registered_client):
    client, _user_id = registered_client
    await client.post("/api/consents", json={"kind": "ai_processing", "version": "v1"})
    await client.delete("/api/consents/ai_processing")

    by_kind = {c["kind"]: c for c in (await client.get("/api/consents")).json()}
    assert by_kind["health_data"] == {
        **by_kind["health_data"], "required": True, "granted": True, "revoked_at": None
    }
    assert by_kind["ai_processing"]["required"] is False
    assert by_kind["ai_processing"]["granted"] is False
    assert by_kind["ai_processing"]["revoked_at"] is not None


async def test_revoking_ai_processing_cuts_off_iafood(registered_client):
    client, _user_id = registered_client
    await client.post("/api/consents", json={"kind": "ai_processing", "version": "v1"})
    await client.delete("/api/consents/ai_processing")
    resp = await client.post("/api/ai/diet-plan", json={"num_days": 1})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "AI_CONSENT_REQUIRED"
