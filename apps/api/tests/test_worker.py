"""Tests del bucle de recordatorios del worker (sección 19, Fase 3) — BD y
Redis reales, pero `send_push` siempre sustituido: nunca se llama a un
servicio de push real desde los tests."""

import uuid
from datetime import datetime

from sqlalchemy import text

from myfood.worker import _redis, run_tick


async def test_run_tick_sends_and_deduplicates(monkeypatch, superuser_conn, two_users):
    user_a, _user_b = two_users
    sent_to: list = []

    def _fake_send_push(sub, payload):
        sent_to.append((sub.endpoint, payload))

    monkeypatch.setattr("myfood.worker.send_push", _fake_send_push)

    rule_id = (
        await superuser_conn.execute(
            text(
                "INSERT INTO notification_rules "
                "(id, user_id, kind, schedule, quiet_from, quiet_to) "
                "VALUES (gen_random_uuid(), :uid, 'water', "
                "'{\"times\": [\"10:00\"]}'::jsonb, '00:00', '00:00') RETURNING id"
            ),
            {"uid": str(user_a)},
        )
    ).scalar_one()
    endpoint = f"https://push.example.com/{uuid.uuid4()}"
    await superuser_conn.execute(
        text(
            "INSERT INTO push_subscriptions (id, user_id, endpoint, p256dh, auth) "
            "VALUES (gen_random_uuid(), :uid, :endpoint, 'p', 'a')"
        ),
        {"uid": str(user_a), "endpoint": endpoint},
    )
    await superuser_conn.commit()

    # limpia cualquier marca de deduplicación de una ejecución anterior de este test
    await _redis.delete(f"notif-sent:{rule_id}:2026-01-15:10:00:00")

    now = datetime(2026, 1, 15, 10, 0)
    sent_count = await run_tick(now)
    assert sent_count == 1
    assert sent_to == [(endpoint, {"title": "MyFood", "body": "Hora de beber agua."})]

    # segundo tick, mismo minuto exacto -> no debe reenviar (deduplicado)
    sent_to.clear()
    sent_count_2 = await run_tick(now)
    assert sent_count_2 == 0
    assert sent_to == []

    await superuser_conn.execute(
        text("DELETE FROM push_subscriptions WHERE endpoint = :e"), {"e": endpoint}
    )
    await superuser_conn.execute(
        text("DELETE FROM notification_rules WHERE id = :id"), {"id": str(rule_id)}
    )
    await superuser_conn.commit()
    await _redis.delete(f"notif-sent:{rule_id}:2026-01-15:10:00:00")


async def test_run_tick_skips_disabled_rules(monkeypatch, superuser_conn, two_users):
    user_a, _user_b = two_users
    called = {"n": 0}
    monkeypatch.setattr(
        "myfood.worker.send_push", lambda sub, payload: called.__setitem__("n", called["n"] + 1)
    )

    rule_id = (
        await superuser_conn.execute(
            text(
                "INSERT INTO notification_rules "
                "(id, user_id, kind, schedule, quiet_from, quiet_to, is_enabled) "
                "VALUES (gen_random_uuid(), :uid, 'water', "
                "'{\"times\": [\"10:00\"]}'::jsonb, '00:00', '00:00', FALSE) RETURNING id"
            ),
            {"uid": str(user_a)},
        )
    ).scalar_one()
    await superuser_conn.commit()

    await run_tick(datetime(2026, 1, 15, 10, 0))
    assert called["n"] == 0

    await superuser_conn.execute(
        text("DELETE FROM notification_rules WHERE id = :id"), {"id": str(rule_id)}
    )
    await superuser_conn.commit()


async def test_run_tick_one_failing_subscription_does_not_block_others(
    monkeypatch, superuser_conn, two_users
):
    """Regresión: un fallo de red enviando a UN suscriptor abortaba todo el
    tick (nunca llegaba al `commit()`), bloqueando también el envío a los
    demás suscriptores de la misma regla."""
    user_a, _user_b = two_users
    sent_to: list = []

    def _flaky_send_push(sub, payload):
        if sub.endpoint.endswith("/broken"):
            raise ConnectionError("servicio de push caído")
        sent_to.append(sub.endpoint)

    monkeypatch.setattr("myfood.worker.send_push", _flaky_send_push)

    rule_id = (
        await superuser_conn.execute(
            text(
                "INSERT INTO notification_rules "
                "(id, user_id, kind, schedule, quiet_from, quiet_to) "
                "VALUES (gen_random_uuid(), :uid, 'water', "
                "'{\"times\": [\"10:00\"]}'::jsonb, '00:00', '00:00') RETURNING id"
            ),
            {"uid": str(user_a)},
        )
    ).scalar_one()
    broken_endpoint = f"https://push.example.com/{uuid.uuid4()}/broken"
    working_endpoint = f"https://push.example.com/{uuid.uuid4()}/ok"
    for endpoint in (broken_endpoint, working_endpoint):
        await superuser_conn.execute(
            text(
                "INSERT INTO push_subscriptions (id, user_id, endpoint, p256dh, auth) "
                "VALUES (gen_random_uuid(), :uid, :endpoint, 'p', 'a')"
            ),
            {"uid": str(user_a), "endpoint": endpoint},
        )
    await superuser_conn.commit()

    now = datetime(2026, 1, 15, 10, 0)
    await _redis.delete(f"notif-sent:{rule_id}:2026-01-15:10:00:00")
    sent_count = await run_tick(now)

    assert sent_count == 1
    assert sent_to == [working_endpoint]  # el roto no bloqueó el envío al bueno

    await superuser_conn.execute(
        text("DELETE FROM push_subscriptions WHERE endpoint IN (:a, :b)"),
        {"a": broken_endpoint, "b": working_endpoint},
    )
    await superuser_conn.execute(
        text("DELETE FROM notification_rules WHERE id = :id"), {"id": str(rule_id)}
    )
    await superuser_conn.commit()
    await _redis.delete(f"notif-sent:{rule_id}:2026-01-15:10:00:00")
