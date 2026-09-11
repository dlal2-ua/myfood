"""Tests de CRUD de reglas de recordatorio (sección 9, Fase 3)."""

from sqlalchemy import text


async def test_create_and_list_water_rule(registered_client):
    client, _user_id = registered_client
    resp = await client.post(
        "/api/notification-rules",
        json={"kind": "water", "schedule": {"times": ["10:00", "16:00"]}},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["kind"] == "water"
    assert body["is_enabled"] is True
    assert body["quiet_from"] == "23:00:00"

    listed = await client.get("/api/notification-rules")
    assert any(r["id"] == body["id"] for r in listed.json())


async def test_filter_by_kind(registered_client):
    client, _user_id = registered_client
    await client.post(
        "/api/notification-rules", json={"kind": "water", "schedule": {"times": ["10:00"]}}
    )
    await client.post(
        "/api/notification-rules",
        json={"kind": "supplement", "schedule": {"time": "09:00", "message": "Creatina"}},
    )

    water_only = await client.get("/api/notification-rules", params={"kind": "water"})
    assert all(r["kind"] == "water" for r in water_only.json())


async def test_update_rule_toggle_and_schedule(registered_client):
    client, _user_id = registered_client
    created = await client.post(
        "/api/notification-rules", json={"kind": "water", "schedule": {"times": ["10:00"]}}
    )
    rule_id = created.json()["id"]

    resp = await client.patch(
        f"/api/notification-rules/{rule_id}",
        json={"is_enabled": False, "schedule": {"times": ["11:00", "17:00"]}},
    )
    assert resp.status_code == 200
    assert resp.json()["is_enabled"] is False
    assert resp.json()["schedule"] == {"times": ["11:00", "17:00"]}


async def test_delete_rule(registered_client):
    client, _user_id = registered_client
    created = await client.post(
        "/api/notification-rules", json={"kind": "water", "schedule": {"times": ["10:00"]}}
    )
    rule_id = created.json()["id"]

    resp = await client.delete(f"/api/notification-rules/{rule_id}")
    assert resp.status_code == 204

    listed = await client.get("/api/notification-rules")
    assert all(r["id"] != rule_id for r in listed.json())


async def test_invalid_kind_rejected(registered_client):
    client, _user_id = registered_client
    resp = await client.post(
        "/api/notification-rules", json={"kind": "not-a-real-kind", "schedule": {}}
    )
    assert resp.status_code == 422


async def test_cross_user_isolation(registered_client, two_users, superuser_conn):
    client, _own_user_id = registered_client
    user_a, _user_b = two_users

    other_rule_id = (
        await superuser_conn.execute(
            text(
                "INSERT INTO notification_rules (id, user_id, kind, schedule) "
                "VALUES (gen_random_uuid(), :uid, 'water', '{\"times\": [\"10:00\"]}'::jsonb) "
                "RETURNING id"
            ),
            {"uid": str(user_a)},
        )
    ).scalar_one()
    await superuser_conn.commit()

    resp = await client.patch(
        f"/api/notification-rules/{other_rule_id}", json={"is_enabled": False}
    )
    assert resp.status_code == 404

    resp2 = await client.delete(f"/api/notification-rules/{other_rule_id}")
    assert resp2.status_code == 404

    await superuser_conn.execute(
        text("DELETE FROM notification_rules WHERE id = :id"), {"id": str(other_rule_id)}
    )
    await superuser_conn.commit()
