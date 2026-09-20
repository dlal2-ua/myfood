"""Contenido dinámico de los avisos, avisos de stock bajo, `/supplements/today` y recordatorios por
horario de suplemento."""

import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from myfood.db.models import NotificationRule
from myfood.db.session import AdminSessionLocal
from myfood.notification_content import build_notification, low_stock_notifications
from myfood.worker import _redis, run_tick

pytestmark = pytest.mark.asyncio

MADRID = ZoneInfo("Europe/Madrid")


def _rule(user_id, kind, schedule):
    return NotificationRule(
        id=uuid.uuid4(), user_id=user_id, kind=kind, is_enabled=True, schedule=schedule
    )


async def _build(rule, hour=10, minute=0, day=date(2026, 1, 15)):
    now = datetime(day.year, day.month, day.day, hour, minute, tzinfo=MADRID)
    async with AdminSessionLocal() as session:
        return await build_notification(session, rule, now)


async def _new_supplement(client, name="Magnesio", **extra):
    resp = await client.post(
        "/api/supplements",
        json={"name": name, "type": "mineral", "dose_amount": 300, "dose_unit": "mg", **extra},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _schedule(client, supplement_id, time_of_day="09:00", days=None, remind=False):
    body = {"time_of_day": time_of_day, "remind": remind}
    if days is not None:
        body["days_of_week"] = days
    resp = await client.post(f"/api/supplements/{supplement_id}/schedules", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- agua ----------------------------------------------------------------------------------------


async def test_the_water_notice_says_how_much_is_left_and_offers_a_glass(registered_client):
    client, user_id = registered_client
    await client.put("/api/water/settings", json={"mode": "manual", "daily_target_ml": 2000})
    await client.post("/api/water/log", json={"log_date": "2026-01-15", "ml": 500})

    payload = await _build(_rule(user_id, "water", {"times": ["10:00"]}))

    assert payload["body"] == "Te faltan 1500 ml para tu objetivo de hoy."
    assert payload["data"] == {"kind": "water", "ml": 200, "url": "/water"}
    assert payload["actions"] == [{"action": "add-water", "title": "+200 ml"}]


async def test_no_water_notice_once_the_goal_is_reached(registered_client):
    client, user_id = registered_client
    await client.put("/api/water/settings", json={"mode": "manual", "daily_target_ml": 1000})
    await client.post("/api/water/log", json={"log_date": "2026-01-15", "ml": 1000})
    assert await _build(_rule(user_id, "water", {"times": ["10:00"]})) is None


async def test_a_custom_message_replaces_the_text_but_keeps_the_actions(registered_client):
    client, user_id = registered_client
    payload = await _build(_rule(user_id, "water", {"times": ["10:00"], "message": "¡Agua!"}))
    assert payload["body"] == "¡Agua!"
    assert payload["actions"]


# --- suplementos ---------------------------------------------------------------------------------


async def test_the_supplement_notice_names_the_supplement_and_dose(registered_client):
    client, user_id = registered_client
    supplement = await _new_supplement(client)
    schedule = await _schedule(client, supplement["id"], "09:00")

    payload = await _build(
        _rule(
            user_id,
            "supplement",
            {"time": "09:00", "supplement_id": supplement["id"], "schedule_id": schedule["id"]},
        ),
        hour=9,
        day=date(2026, 1, 15),  # jueves
    )

    assert payload["body"] == "Toca Magnesio (300 mg)."
    assert [a["action"] for a in payload["actions"]] == ["supplement-taken", "supplement-skip"]
    assert payload["data"]["supplement_id"] == supplement["id"]


async def test_no_supplement_notice_when_the_dose_was_already_logged(registered_client):
    client, user_id = registered_client
    supplement = await _new_supplement(client)
    schedule = await _schedule(client, supplement["id"], "09:00")
    await client.post(f"/api/supplements/{supplement['id']}/log", json={"log_date": "2026-01-15"})
    rule = _rule(
        user_id,
        "supplement",
        {"time": "09:00", "supplement_id": supplement["id"], "schedule_id": schedule["id"]},
    )
    assert await _build(rule, hour=9) is None


async def test_with_two_doses_a_day_one_log_only_silences_the_first_reminder(registered_client):
    client, user_id = registered_client
    supplement = await _new_supplement(client)
    morning = await _schedule(client, supplement["id"], "09:00")
    evening = await _schedule(client, supplement["id"], "21:00")
    await client.post(f"/api/supplements/{supplement['id']}/log", json={"log_date": "2026-01-15"})

    def rule(schedule):
        return _rule(
            user_id,
            "supplement",
            {
                "time": schedule["time_of_day"],
                "supplement_id": supplement["id"],
                "schedule_id": schedule["id"],
            },
        )

    assert await _build(rule(morning), hour=9) is None
    assert (await _build(rule(evening), hour=21))["body"].startswith("Toca Magnesio")


async def test_an_inactive_supplement_sends_no_notice(registered_client):
    client, user_id = registered_client
    supplement = await _new_supplement(client)
    await client.patch(f"/api/supplements/{supplement['id']}", json={"is_active": False})
    rule = _rule(user_id, "supplement", {"time": "09:00", "supplement_id": supplement["id"]})
    assert await _build(rule, hour=9) is None


# --- comida y peso -------------------------------------------------------------------------------


async def test_the_meal_notice_is_skipped_when_that_meal_is_already_logged(
    registered_client, test_food
):
    client, user_id = registered_client
    rule = _rule(user_id, "meal", {"time": "14:00", "meal_type": "lunch"})
    payload = await _build(rule, hour=14)
    assert payload["body"] == "Cuando termines, apunta la comida."
    assert payload["data"]["url"] == "/log"

    await client.post(
        "/api/log/food",
        json={
            "log_date": "2026-01-15",
            "meal_type": "lunch",
            "food_id": str(test_food),
            "grams": 100,
        },
    )
    assert await _build(rule, hour=14) is None


async def test_the_weigh_in_notice_is_neutral_and_skipped_once_weighed(registered_client):
    client, user_id = registered_client
    rule = _rule(user_id, "weigh_in", {"time": "08:00"})
    payload = await _build(rule, hour=8)
    assert payload["body"] == "Cuando quieras, apunta tu peso de hoy."

    await client.post("/api/measurements", json={"measured_on": "2026-01-15", "weight_kg": 70})
    assert await _build(rule, hour=8) is None


# --- reglas: validación y «no molestar» ---------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "schedule"),
    [
        ("water", {}),
        ("water", {"times": []}),
        ("water", {"times": ["25:00"]}),
        ("water", {"times": [f"{h:02d}:00" for h in range(9, 19)]}),
        ("supplement", {}),
        ("supplement", {"time": "9am"}),
        ("meal", {"time": "14:00"}),
        ("meal", {"time": "14:00", "meal_type": "brunch"}),
        ("weigh_in", {"time": "08:00", "days_of_week": [0]}),
        ("weigh_in", {"time": "08:00", "days_of_week": []}),
    ],
)
async def test_a_malformed_schedule_is_rejected(registered_client, kind, schedule):
    client, _ = registered_client
    resp = await client.post("/api/notification-rules", json={"kind": kind, "schedule": schedule})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_SCHEDULE"


async def test_meal_and_weigh_in_rules_can_be_created(registered_client):
    client, _ = registered_client
    meal = await client.post(
        "/api/notification-rules",
        json={"kind": "meal", "schedule": {"time": "14:00", "meal_type": "lunch"}},
    )
    weigh = await client.post(
        "/api/notification-rules",
        json={"kind": "weigh_in", "schedule": {"time": "08:00", "days_of_week": [1, 4]}},
    )
    assert meal.status_code == 201
    assert weigh.status_code == 201


async def test_updating_a_schedule_is_validated_too(registered_client):
    client, _ = registered_client
    rule = (
        await client.post(
            "/api/notification-rules", json={"kind": "water", "schedule": {"times": ["10:00"]}}
        )
    ).json()
    bad = await client.patch(f"/api/notification-rules/{rule['id']}", json={"schedule": {}})
    assert bad.status_code == 422


async def test_quiet_hours_apply_to_all_rules_and_new_rules_inherit_them(registered_client):
    client, _ = registered_client
    default = (await client.get("/api/notification-rules/quiet-hours")).json()
    assert default == {"quiet_from": "23:00:00", "quiet_to": "08:00:00"}

    first = (
        await client.post(
            "/api/notification-rules", json={"kind": "water", "schedule": {"times": ["10:00"]}}
        )
    ).json()
    resp = await client.put(
        "/api/notification-rules/quiet-hours", json={"quiet_from": "22:00", "quiet_to": "09:30"}
    )
    assert resp.status_code == 200

    second = (
        await client.post(
            "/api/notification-rules",
            json={"kind": "weigh_in", "schedule": {"time": "10:00"}},
        )
    ).json()
    listed = {r["id"]: r for r in (await client.get("/api/notification-rules")).json()}
    assert listed[first["id"]]["quiet_from"] == "22:00:00"
    assert listed[second["id"]]["quiet_to"] == "09:30:00"
    assert (await client.get("/api/notification-rules/quiet-hours")).json() == {
        "quiet_from": "22:00:00",
        "quiet_to": "09:30:00",
    }


# --- /supplements/today, recordatorio por horario y coste ---------------------------------------


def _local_now(client_tz="Europe/Madrid"):
    return datetime.now(ZoneInfo(client_tz))


async def test_today_lists_the_doses_of_today_with_their_state(registered_client):
    client, _ = registered_client
    now = _local_now()
    supplement = await _new_supplement(client)
    early = (now - timedelta(hours=2)).strftime("%H:%M")
    late = (now + timedelta(hours=2)).strftime("%H:%M")
    if now.hour < 2 or now.hour > 21:
        pytest.skip("la ventana de la prueba cruza la medianoche")
    await _schedule(client, supplement["id"], early)
    await _schedule(client, supplement["id"], late)

    body = (await client.get("/api/supplements/today")).json()

    assert body["date"] == now.date().isoformat()
    assert [d["status"] for d in body["doses"]] == ["overdue", "pending"]
    assert body["pending_count"] == 2
    assert body["doses"][0]["supplement_name"] == "Magnesio"

    await client.post(f"/api/supplements/{supplement['id']}/log", json={"log_date": body["date"]})
    after = (await client.get("/api/supplements/today")).json()
    assert [d["status"] for d in after["doses"]] == ["taken", "pending"]
    assert after["pending_count"] == 1


async def test_today_marks_a_skipped_dose_and_ignores_other_weekdays_and_inactive_supplements(
    registered_client,
):
    client, _ = registered_client
    now = _local_now()
    other_day = [d for d in range(1, 8) if d != now.isoweekday()]
    supplement = await _new_supplement(client)
    await _schedule(client, supplement["id"], "23:59")
    await _schedule(client, supplement["id"], "10:00", days=other_day)
    inactive = await _new_supplement(client, name="Hierro")
    await _schedule(client, inactive["id"], "10:00")
    await client.patch(f"/api/supplements/{inactive['id']}", json={"is_active": False})
    await client.post(
        f"/api/supplements/{supplement['id']}/log",
        json={"log_date": now.date().isoformat(), "skipped": True},
    )

    doses = (await client.get("/api/supplements/today")).json()["doses"]

    assert [(d["supplement_name"], d["status"]) for d in doses] == [("Magnesio", "skipped")]


async def test_today_is_empty_without_supplements(registered_client):
    client, _ = registered_client
    assert (await client.get("/api/supplements/today")).json()["doses"] == []


async def test_adding_a_schedule_with_remind_creates_its_notification_rule(registered_client):
    client, _ = registered_client
    supplement = await _new_supplement(client)
    schedule = await _schedule(client, supplement["id"], "09:30", days=[1, 2, 3], remind=True)
    assert schedule["has_reminder"] is True

    rules = (await client.get("/api/notification-rules", params={"kind": "supplement"})).json()
    assert len(rules) == 1
    assert rules[0]["schedule"] == {
        "time": "09:30",
        "days_of_week": [1, 2, 3],
        "supplement_id": supplement["id"],
        "schedule_id": schedule["id"],
    }
    detail = (await client.get(f"/api/supplements/{supplement['id']}")).json()
    assert detail["schedules"][0]["has_reminder"] is True


async def test_a_schedule_without_remind_creates_no_rule_and_deleting_removes_the_rule(
    registered_client,
):
    client, _ = registered_client
    supplement = await _new_supplement(client)
    plain = await _schedule(client, supplement["id"], "09:00")
    reminded = await _schedule(client, supplement["id"], "21:00", remind=True)
    assert plain["has_reminder"] is False

    assert (
        await client.get("/api/notification-rules", params={"kind": "supplement"})
    ).json().__len__() == 1

    await client.delete(f"/api/supplements/{supplement['id']}/schedules/{reminded['id']}")
    assert (await client.get("/api/notification-rules", params={"kind": "supplement"})).json() == []


async def test_the_monthly_cost_uses_price_doses_and_schedule(registered_client):
    client, _ = registered_client
    supplement = await _new_supplement(client, price_per_container=15.0, doses_per_container=60)
    await _schedule(client, supplement["id"], "09:00")  # todos los días -> 30 dosis al mes

    listed = (await client.get("/api/supplements")).json()

    assert listed["items"][0]["monthly_cost"] == 7.5
    assert listed["total_monthly_cost"] == 7.5


async def test_the_monthly_cost_is_unknown_without_price_or_schedule(registered_client):
    client, _ = registered_client
    no_price = await _new_supplement(client, name="A", doses_per_container=30)
    no_schedule = await _new_supplement(
        client, name="B", price_per_container=10, doses_per_container=30
    )
    await _schedule(client, no_price["id"], "09:00")

    body = (await client.get("/api/supplements")).json()

    assert all(i["monthly_cost"] is None for i in body["items"])
    assert body["total_monthly_cost"] is None
    assert no_schedule["monthly_cost"] is None


# --- stock bajo -----------------------------------------------------------------------------------


async def test_low_stock_notice_counts_the_days_left(registered_client):
    client, user_id = registered_client
    supplement = await _new_supplement(client, doses_per_container=4)
    await _schedule(client, supplement["id"], "09:00")

    async with AdminSessionLocal() as session:
        found = [
            n for n in await low_stock_notifications(session) if n[1] == uuid.UUID(supplement["id"])
        ]

    assert len(found) == 1
    assert found[0][0] == user_id
    assert found[0][2]["body"] == "Te quedan 4 días de Magnesio."


async def test_no_low_stock_notice_with_plenty_left_or_without_a_schedule(registered_client):
    client, _ = registered_client
    plenty = await _new_supplement(client, name="Plenty", doses_per_container=90)
    await _schedule(client, plenty["id"], "09:00")
    unscheduled = await _new_supplement(client, name="Unscheduled", doses_per_container=2)

    async with AdminSessionLocal() as session:
        ids = {n[1] for n in await low_stock_notifications(session)}

    assert uuid.UUID(plenty["id"]) not in ids
    assert uuid.UUID(unscheduled["id"]) not in ids


async def test_the_worker_sends_the_low_stock_notice_once_a_day_at_ten_local(
    registered_client, superuser_conn, monkeypatch
):
    client, user_id = registered_client
    supplement = await _new_supplement(client, name="Zinc", doses_per_container=3)
    await _schedule(client, supplement["id"], "09:00")
    endpoint = f"https://push.example.com/{uuid.uuid4()}"
    await superuser_conn.execute(
        text(
            "INSERT INTO push_subscriptions (id, user_id, endpoint, p256dh, auth) "
            "VALUES (gen_random_uuid(), :uid, :e, 'p', 'a')"
        ),
        {"uid": str(user_id), "e": endpoint},
    )
    await superuser_conn.commit()
    sent: list = []
    monkeypatch.setattr(
        "myfood.worker.send_push", lambda sub, payload: sent.append((sub.endpoint, payload))
    )
    day = "2031-03-05"
    key = f"notif-sent:lowstock-{supplement['id']}:{day}:10:00:00"
    await _redis.delete(key)

    ten_local = datetime(2031, 3, 5, 10, 0, tzinfo=MADRID).astimezone(UTC)
    first = await run_tick(ten_local)
    second = await run_tick(ten_local)
    other_hour = await run_tick(ten_local + timedelta(hours=3))

    assert first >= 1
    assert any("Zinc" in p["body"] for e, p in sent if e == endpoint)
    assert second == 0
    assert other_hour == 0
    await _redis.delete(key)


async def test_the_worker_uses_each_users_timezone(registered_client, superuser_conn, monkeypatch):
    client, user_id = registered_client
    await superuser_conn.execute(
        text("UPDATE users SET timezone = 'America/Mexico_City' WHERE id = :id"),
        {"id": str(user_id)},
    )
    rule = (
        await client.post(
            "/api/notification-rules",
            json={
                "kind": "weigh_in",
                "schedule": {"time": "08:00"},
                "quiet_from": "00:00",
                "quiet_to": "00:00",
            },
        )
    ).json()
    endpoint = f"https://push.example.com/{uuid.uuid4()}"
    await superuser_conn.execute(
        text(
            "INSERT INTO push_subscriptions (id, user_id, endpoint, p256dh, auth) "
            "VALUES (gen_random_uuid(), :uid, :e, 'p', 'a')"
        ),
        {"uid": str(user_id), "e": endpoint},
    )
    await superuser_conn.commit()
    sent: list = []
    monkeypatch.setattr("myfood.worker.send_push", lambda sub, payload: sent.append(payload))
    key = f"notif-sent:{rule['id']}:2031-06-10:08:00:00"
    await _redis.delete(key)

    # 08:00 en Ciudad de México (UTC-6, sin horario de verano) = 14:00 UTC
    at_madrid_eight = datetime(2031, 6, 10, 6, 0, tzinfo=UTC)  # 08:00 en Madrid (CEST)
    assert await run_tick(at_madrid_eight) == 0, "a esa hora en México aún es de noche"
    assert await run_tick(datetime(2031, 6, 10, 14, 0, tzinfo=UTC)) == 1
    assert sent[0]["body"] == "Cuando quieras, apunta tu peso de hoy."
    await _redis.delete(key)


async def test_run_tick_needs_an_aware_datetime():
    with pytest.raises(ValueError):
        await run_tick(datetime(2026, 1, 15, 10, 0))
