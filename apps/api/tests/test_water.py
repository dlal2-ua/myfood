"""Tests del control de agua (documento 2, sección 6.6/12.6, Fase 3)."""

from sqlalchemy import text


async def test_settings_default_on_first_read(registered_client):
    client, _user_id = registered_client
    resp = await client.get("/api/water/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "auto"
    assert body["daily_target_ml"] == 2500  # default de la migración, sin perfil/peso aún
    assert body["containers"] == [
        {"label": "Vaso", "ml": 200},
        {"label": "Botella", "ml": 500},
    ]


async def test_manual_mode_uses_stored_target(registered_client):
    client, _user_id = registered_client
    resp = await client.put(
        "/api/water/settings", json={"mode": "manual", "daily_target_ml": 3000}
    )
    assert resp.status_code == 200
    assert resp.json()["mode"] == "manual"
    assert resp.json()["daily_target_ml"] == 3000

    resp2 = await client.get("/api/water/settings")
    assert resp2.json()["daily_target_ml"] == 3000


async def test_auto_mode_uses_formula_when_profile_and_weight_present(registered_client):
    # sex y weight_kg van cifrados en reposo (R4) — se fijan a través de la
    # propia API (que cifra al escribir), nunca con SQL crudo.
    client, _user_id = registered_client
    await client.put("/api/profile", json={"sex": "male"})
    await client.post(
        "/api/measurements", json={"measured_on": "2026-01-10", "weight_kg": 80}
    )

    resp = await client.get("/api/water/settings")
    assert resp.status_code == 200
    # water_target_ml("male", 80) = max(2500, 80*33) = 2640
    assert resp.json()["daily_target_ml"] == 2640


async def test_custom_containers(registered_client):
    client, _user_id = registered_client
    resp = await client.put(
        "/api/water/settings",
        json={"containers": [{"label": "Taza", "ml": 250}]},
    )
    assert resp.status_code == 200
    assert resp.json()["containers"] == [{"label": "Taza", "ml": 250}]


async def test_log_water_and_day_totals(registered_client):
    client, _user_id = registered_client
    r1 = await client.post("/api/water/log", json={"log_date": "2026-01-15", "ml": 200})
    r2 = await client.post("/api/water/log", json={"log_date": "2026-01-15", "ml": 500})
    assert r1.status_code == 201
    assert r2.status_code == 201

    day = await client.get("/api/water/log", params={"date": "2026-01-15"})
    assert day.status_code == 200
    body = day.json()
    assert body["total_ml"] == 700
    assert len(body["entries"]) == 2
    assert body["target_ml"] == 2500


async def test_delete_water_log_entry(registered_client):
    client, _user_id = registered_client
    created = await client.post("/api/water/log", json={"log_date": "2026-01-16", "ml": 300})
    entry_id = created.json()["id"]

    delete_resp = await client.delete(f"/api/water/log/{entry_id}")
    assert delete_resp.status_code == 204

    day = await client.get("/api/water/log", params={"date": "2026-01-16"})
    assert day.json()["total_ml"] == 0


async def test_water_log_ml_bounds_rejected(registered_client):
    client, _user_id = registered_client
    resp = await client.post("/api/water/log", json={"log_date": "2026-01-15", "ml": 0})
    assert resp.status_code == 422
    resp2 = await client.post("/api/water/log", json={"log_date": "2026-01-15", "ml": 10000})
    assert resp2.status_code == 422


async def test_cross_user_isolation_on_delete(registered_client, two_users, superuser_conn):
    client, _own_user_id = registered_client
    user_a, _user_b = two_users

    other_entry_id = (
        await superuser_conn.execute(
            text(
                "INSERT INTO water_log (id, user_id, log_date, ml) "
                "VALUES (gen_random_uuid(), :uid, CURRENT_DATE, 200) RETURNING id"
            ),
            {"uid": str(user_a)},
        )
    ).scalar_one()
    await superuser_conn.commit()

    resp = await client.delete(f"/api/water/log/{other_entry_id}")
    assert resp.status_code == 404

    await superuser_conn.execute(
        text("DELETE FROM water_log WHERE id = :id"), {"id": str(other_entry_id)}
    )
    await superuser_conn.commit()
