"""Suplementación — catálogo, horarios, stock y registro de tomas (Fase 3)."""

import uuid
from datetime import date

import pytest

pytestmark = pytest.mark.asyncio


async def _create_supplement(client, **overrides):
    body = {
        "name": "Creatina monohidrato",
        "type": "creatine",
        "dose_amount": 5,
        "dose_unit": "g",
    }
    body.update(overrides)
    resp = await client.post("/api/supplements", json=body)
    return resp


async def _add_daily_schedule(client, supplement_id):
    """Un horario diario (los 7 días) equivale a 1 dosis/día para el cálculo
    simple de días de stock restantes."""
    return await client.post(
        f"/api/supplements/{supplement_id}/schedules",
        json={"time_of_day": "08:00:00", "days_of_week": [1, 2, 3, 4, 5, 6, 7]},
    )


async def test_create_supplement_without_container_has_no_stock(registered_client):
    client, _ = registered_client
    resp = await _create_supplement(client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Creatina monohidrato"
    assert body["doses_per_container"] is None
    assert body["doses_remaining"] is None
    assert body["days_remaining"] is None
    assert body["low_stock"] is False
    assert body["is_active"] is True


async def test_create_supplement_with_container_seeds_stock(registered_client):
    client, _ = registered_client
    resp = await _create_supplement(client, doses_per_container=60, price_per_container=12.5)
    assert resp.status_code == 201
    body = resp.json()
    assert body["doses_per_container"] == 60
    assert body["doses_remaining"] == 60.0
    assert body["price_per_container"] == 12.5
    assert body["last_restock_at"] is None
    # sin horarios todavía no se puede estimar consumo diario
    assert body["days_remaining"] is None
    assert body["low_stock"] is False


async def test_create_supplement_unknown_food_is_404(registered_client):
    client, _ = registered_client
    resp = await _create_supplement(client, food_id=str(uuid.uuid4()))
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "FOOD_NOT_FOUND"


async def test_create_supplement_invalid_dose_amount_is_422(registered_client):
    client, _ = registered_client
    resp = await _create_supplement(client, dose_amount=0)
    assert resp.status_code == 422


async def test_create_supplement_with_real_food(registered_client, test_food):
    client, _ = registered_client
    resp = await _create_supplement(
        client, name="Proteína de suero", type="protein", food_id=str(test_food)
    )
    assert resp.status_code == 201
    assert resp.json()["food_id"] == str(test_food)


async def test_list_supplements_active_only_by_default(registered_client):
    client, _ = registered_client
    created = await _create_supplement(client)
    supplement_id = created.json()["id"]
    await client.patch(f"/api/supplements/{supplement_id}", json={"is_active": False})

    active_only = await client.get("/api/supplements")
    assert active_only.json()["items"] == []

    with_inactive = await client.get("/api/supplements", params={"include_inactive": "true"})
    items = with_inactive.json()["items"]
    assert len(items) == 1
    assert items[0]["is_active"] is False


async def test_get_supplement_detail_includes_schedules(registered_client):
    client, _ = registered_client
    created = await _create_supplement(client)
    supplement_id = created.json()["id"]
    await _add_daily_schedule(client, supplement_id)

    resp = await client.get(f"/api/supplements/{supplement_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["schedules"]) == 1
    assert body["schedules"][0]["time_of_day"] == "08:00"
    assert body["schedules"][0]["days_of_week"] == [1, 2, 3, 4, 5, 6, 7]
    assert body["schedules"][0]["with_food"] is False


async def test_get_unknown_supplement_is_404(registered_client):
    client, _ = registered_client
    resp = await client.get(f"/api/supplements/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "SUPPLEMENT_NOT_FOUND"


async def test_add_schedule_invalid_days_of_week_is_422(registered_client):
    client, _ = registered_client
    created = await _create_supplement(client)
    supplement_id = created.json()["id"]

    empty = await client.post(
        f"/api/supplements/{supplement_id}/schedules",
        json={"time_of_day": "08:00:00", "days_of_week": []},
    )
    assert empty.status_code == 422

    out_of_range = await client.post(
        f"/api/supplements/{supplement_id}/schedules",
        json={"time_of_day": "08:00:00", "days_of_week": [0, 8]},
    )
    assert out_of_range.status_code == 422


async def test_delete_schedule(registered_client):
    client, _ = registered_client
    created = await _create_supplement(client)
    supplement_id = created.json()["id"]
    schedule = await _add_daily_schedule(client, supplement_id)
    schedule_id = schedule.json()["id"]

    resp = await client.delete(f"/api/supplements/{supplement_id}/schedules/{schedule_id}")
    assert resp.status_code == 204

    detail = await client.get(f"/api/supplements/{supplement_id}")
    assert detail.json()["schedules"] == []


async def test_delete_nonexistent_schedule_is_404(registered_client):
    client, _ = registered_client
    created = await _create_supplement(client)
    supplement_id = created.json()["id"]

    resp = await client.delete(f"/api/supplements/{supplement_id}/schedules/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "SCHEDULE_NOT_FOUND"


async def test_log_dose_decrements_stock(registered_client):
    client, _ = registered_client
    created = await _create_supplement(client, doses_per_container=10)
    supplement_id = created.json()["id"]

    resp = await client.post(
        f"/api/supplements/{supplement_id}/log",
        json={"log_date": date.today().isoformat()},
    )
    assert resp.status_code == 201
    assert resp.json()["skipped"] is False
    assert resp.json()["supplement_name"] == "Creatina monohidrato"

    detail = await client.get(f"/api/supplements/{supplement_id}")
    assert detail.json()["doses_remaining"] == 9.0


async def test_log_skipped_dose_does_not_decrement_stock(registered_client):
    client, _ = registered_client
    created = await _create_supplement(client, doses_per_container=10)
    supplement_id = created.json()["id"]

    resp = await client.post(
        f"/api/supplements/{supplement_id}/log",
        json={"log_date": date.today().isoformat(), "skipped": True},
    )
    assert resp.status_code == 201
    assert resp.json()["skipped"] is True

    detail = await client.get(f"/api/supplements/{supplement_id}")
    assert detail.json()["doses_remaining"] == 10.0


async def test_log_dose_clamps_stock_at_zero(registered_client):
    client, _ = registered_client
    created = await _create_supplement(client, doses_per_container=1)
    supplement_id = created.json()["id"]

    for _ in range(3):
        await client.post(
            f"/api/supplements/{supplement_id}/log",
            json={"log_date": date.today().isoformat()},
        )

    detail = await client.get(f"/api/supplements/{supplement_id}")
    assert detail.json()["doses_remaining"] == 0.0


async def test_low_stock_flag_appears_at_five_days_remaining(registered_client):
    client, _ = registered_client
    created = await _create_supplement(client, doses_per_container=10)
    supplement_id = created.json()["id"]
    await _add_daily_schedule(client, supplement_id)  # 1 dosis/día

    # 4 tomas -> quedan 6 dosis == 6 días -> todavía no es low stock
    for _ in range(4):
        await client.post(
            f"/api/supplements/{supplement_id}/log",
            json={"log_date": date.today().isoformat()},
        )
    not_yet = await client.get(f"/api/supplements/{supplement_id}")
    assert not_yet.json()["days_remaining"] == 6.0
    assert not_yet.json()["low_stock"] is False

    # una toma más -> quedan 5 dosis == 5 días -> low stock (umbral ≤5)
    await client.post(
        f"/api/supplements/{supplement_id}/log",
        json={"log_date": date.today().isoformat()},
    )
    now_low = await client.get(f"/api/supplements/{supplement_id}")
    assert now_low.json()["days_remaining"] == 5.0
    assert now_low.json()["low_stock"] is True

    listed = await client.get("/api/supplements")
    assert listed.json()["items"][0]["low_stock"] is True


async def test_restock_increases_stock_and_clears_low_stock(registered_client):
    client, _ = registered_client
    created = await _create_supplement(client, doses_per_container=10)
    supplement_id = created.json()["id"]
    await _add_daily_schedule(client, supplement_id)

    for _ in range(5):
        await client.post(
            f"/api/supplements/{supplement_id}/log",
            json={"log_date": date.today().isoformat()},
        )
    low = await client.get(f"/api/supplements/{supplement_id}")
    assert low.json()["low_stock"] is True

    resp = await client.post(
        f"/api/supplements/{supplement_id}/restock", json={"doses_added": 10}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["doses_remaining"] == 15.0
    assert body["last_restock_at"] is not None
    assert body["low_stock"] is False


async def test_restock_without_prior_stock_creates_it(registered_client):
    client, _ = registered_client
    created = await _create_supplement(client)  # sin doses_per_container
    supplement_id = created.json()["id"]

    resp = await client.post(
        f"/api/supplements/{supplement_id}/restock", json={"doses_added": 30}
    )
    assert resp.status_code == 200
    assert resp.json()["doses_remaining"] == 30.0


async def test_restock_invalid_amount_is_422(registered_client):
    client, _ = registered_client
    created = await _create_supplement(client, doses_per_container=10)
    supplement_id = created.json()["id"]

    resp = await client.post(
        f"/api/supplements/{supplement_id}/restock", json={"doses_added": 0}
    )
    assert resp.status_code == 422


async def test_delete_log_entry_reincrements_stock(registered_client):
    client, _ = registered_client
    created = await _create_supplement(client, doses_per_container=10)
    supplement_id = created.json()["id"]

    logged = await client.post(
        f"/api/supplements/{supplement_id}/log",
        json={"log_date": date.today().isoformat()},
    )
    entry_id = logged.json()["id"]
    after_log = await client.get(f"/api/supplements/{supplement_id}")
    assert after_log.json()["doses_remaining"] == 9.0

    resp = await client.delete(f"/api/supplements/log/{entry_id}")
    assert resp.status_code == 204

    after_delete = await client.get(f"/api/supplements/{supplement_id}")
    assert after_delete.json()["doses_remaining"] == 10.0


async def test_delete_skipped_log_entry_does_not_reincrement_stock(registered_client):
    client, _ = registered_client
    created = await _create_supplement(client, doses_per_container=10)
    supplement_id = created.json()["id"]

    logged = await client.post(
        f"/api/supplements/{supplement_id}/log",
        json={"log_date": date.today().isoformat(), "skipped": True},
    )
    entry_id = logged.json()["id"]

    resp = await client.delete(f"/api/supplements/log/{entry_id}")
    assert resp.status_code == 204

    after_delete = await client.get(f"/api/supplements/{supplement_id}")
    assert after_delete.json()["doses_remaining"] == 10.0


async def test_delete_nonexistent_log_entry_is_404(registered_client):
    client, _ = registered_client
    resp = await client.delete(f"/api/supplements/log/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "SUPPLEMENT_LOG_NOT_FOUND"


async def test_get_day_supplement_log_returns_entries_for_date(registered_client):
    client, _ = registered_client
    created = await _create_supplement(client, doses_per_container=10)
    supplement_id = created.json()["id"]
    today = date.today().isoformat()

    await client.post(f"/api/supplements/{supplement_id}/log", json={"log_date": today})
    await client.post(
        f"/api/supplements/{supplement_id}/log", json={"log_date": today, "skipped": True}
    )
    await client.post(
        f"/api/supplements/{supplement_id}/log", json={"log_date": "2020-01-01"}
    )

    resp = await client.get("/api/supplements/log", params={"date": today})
    assert resp.status_code == 200
    body = resp.json()
    assert body["date"] == today
    assert len(body["entries"]) == 2
    assert {e["skipped"] for e in body["entries"]} == {False, True}
    assert body["entries"][0]["supplement_name"] == "Creatina monohidrato"


async def test_patch_supplement_edit_fields_and_deactivate(registered_client):
    client, _ = registered_client
    created = await _create_supplement(client)
    supplement_id = created.json()["id"]

    resp = await client.patch(
        f"/api/supplements/{supplement_id}",
        json={"name": "Creatina (nueva marca)", "notes": "Tomar con agua", "is_active": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Creatina (nueva marca)"
    assert body["notes"] == "Tomar con agua"
    assert body["is_active"] is False


async def test_patch_supplement_sets_container_seeds_stock_if_missing(registered_client):
    client, _ = registered_client
    created = await _create_supplement(client)  # sin envase al crear
    supplement_id = created.json()["id"]
    assert created.json()["doses_remaining"] is None

    resp = await client.patch(
        f"/api/supplements/{supplement_id}", json={"doses_per_container": 20}
    )
    assert resp.status_code == 200
    assert resp.json()["doses_remaining"] == 20.0


async def test_patch_unknown_food_id_is_404(registered_client):
    client, _ = registered_client
    created = await _create_supplement(client)
    supplement_id = created.json()["id"]

    resp = await client.patch(
        f"/api/supplements/{supplement_id}", json={"food_id": str(uuid.uuid4())}
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "FOOD_NOT_FOUND"


async def test_delete_supplement_cascades(registered_client):
    client, _ = registered_client
    created = await _create_supplement(client, doses_per_container=10)
    supplement_id = created.json()["id"]
    await _add_daily_schedule(client, supplement_id)
    await client.post(
        f"/api/supplements/{supplement_id}/log", json={"log_date": date.today().isoformat()}
    )

    resp = await client.delete(f"/api/supplements/{supplement_id}")
    assert resp.status_code == 204

    listed = await client.get("/api/supplements")
    assert listed.json()["items"] == []

    day_log = await client.get(
        "/api/supplements/log", params={"date": date.today().isoformat()}
    )
    assert day_log.json()["entries"] == []


async def test_supplements_cross_user_isolation(registered_client, superuser_conn):
    """R3 — ningún endpoint devuelve ni modifica suplementos, horarios o
    registros de otro usuario."""
    from httpx import ASGITransport, AsyncClient

    from myfood.main import app

    client, _ = registered_client
    created = await _create_supplement(client, doses_per_container=10)
    supplement_id = created.json()["id"]
    schedule = await _add_daily_schedule(client, supplement_id)
    schedule_id = schedule.json()["id"]
    logged = await client.post(
        f"/api/supplements/{supplement_id}/log", json={"log_date": date.today().isoformat()}
    )
    entry_id = logged.json()["id"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as other_client:
        email = f"other-{uuid.uuid4()}@test.myfood"
        other_resp = await other_client.post(
            "/api/auth/register",
            json={"email": email, "password": "correcthorse123", "display_name": "Other"},
        )
        other_id = other_resp.json()["id"]

        assert (await other_client.get("/api/supplements")).json()["items"] == []
        assert (
            await other_client.get(
                "/api/supplements", params={"include_inactive": "true"}
            )
        ).json()["items"] == []

        get_resp = await other_client.get(f"/api/supplements/{supplement_id}")
        assert get_resp.status_code == 404

        patch_resp = await other_client.patch(
            f"/api/supplements/{supplement_id}", json={"name": "Hijacked"}
        )
        assert patch_resp.status_code == 404

        schedule_resp = await other_client.post(
            f"/api/supplements/{supplement_id}/schedules",
            json={"time_of_day": "09:00:00"},
        )
        assert schedule_resp.status_code == 404

        del_schedule_resp = await other_client.delete(
            f"/api/supplements/{supplement_id}/schedules/{schedule_id}"
        )
        assert del_schedule_resp.status_code == 404

        restock_resp = await other_client.post(
            f"/api/supplements/{supplement_id}/restock", json={"doses_added": 5}
        )
        assert restock_resp.status_code == 404

        log_resp = await other_client.post(
            f"/api/supplements/{supplement_id}/log",
            json={"log_date": date.today().isoformat()},
        )
        assert log_resp.status_code == 404

        del_log_resp = await other_client.delete(f"/api/supplements/log/{entry_id}")
        assert del_log_resp.status_code == 404

        other_day_log = await other_client.get(
            "/api/supplements/log", params={"date": date.today().isoformat()}
        )
        assert other_day_log.json()["entries"] == []

        del_resp = await other_client.delete(f"/api/supplements/{supplement_id}")
        assert del_resp.status_code == 404

    from sqlalchemy import text

    await superuser_conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": other_id})
    await superuser_conn.commit()

    # todo lo del usuario original sigue intacto
    detail = await client.get(f"/api/supplements/{supplement_id}")
    assert detail.status_code == 200
    assert len(detail.json()["schedules"]) == 1
    assert detail.json()["doses_remaining"] == 9.0  # sin cambios por el otro usuario
