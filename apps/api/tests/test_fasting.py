"""Ayuno intermitente: temporizador, historial y adherencia (`/fasting`)."""

from datetime import UTC, datetime, timedelta

import pytest


def _ago(hours: float) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours)).isoformat()


async def _start(client, hours_ago=0.0, target=16):
    resp = await client.post(
        "/api/fasting/start", json={"target_hours": target, "started_at": _ago(hours_ago)}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_there_is_no_current_fast_at_first(registered_client):
    client, _ = registered_client
    resp = await client.get("/api/fasting/current")
    assert resp.status_code == 200
    assert resp.json() is None


async def test_starting_a_fast_reports_its_timer(registered_client):
    client, _ = registered_client
    started = await _start(client, hours_ago=4, target=16)

    assert started["target_hours"] == 16
    assert started["elapsed_hours"] == pytest.approx(4, abs=0.05)
    assert started["remaining_hours"] == pytest.approx(12, abs=0.05)
    assert started["eating_window_hours"] == 8
    assert started["reached_target"] is False
    assert started["ended_at"] is None
    assert (await client.get("/api/fasting/current")).json()["id"] == started["id"]


async def test_a_fast_that_reaches_its_target_says_so(registered_client):
    client, _ = registered_client
    started = await _start(client, hours_ago=17, target=16)
    assert started["reached_target"] is True
    assert started["remaining_hours"] == 0


async def test_only_one_fast_can_be_open_at_a_time(registered_client):
    client, _ = registered_client
    await _start(client)
    again = await client.post("/api/fasting/start", json={})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "FASTING_ALREADY_ACTIVE"


async def test_ending_a_fast_closes_it_and_frees_the_slot(registered_client):
    client, _ = registered_client
    started = await _start(client, hours_ago=15, target=16)

    ended = await client.post(f"/api/fasting/{started['id']}/end", json={})

    assert ended.status_code == 200
    assert ended.json()["ended_at"] is not None
    assert ended.json()["reached_target"] is False
    assert (await client.get("/api/fasting/current")).json() is None
    await _start(client)  # ya se puede abrir otro


async def test_a_fast_cannot_be_ended_twice_or_before_it_started(registered_client):
    client, _ = registered_client
    started = await _start(client, hours_ago=2)

    before = await client.post(f"/api/fasting/{started['id']}/end", json={"ended_at": _ago(5)})
    assert before.status_code == 422
    assert before.json()["error"]["code"] == "FASTING_ENDS_BEFORE_START"

    assert (await client.post(f"/api/fasting/{started['id']}/end", json={})).status_code == 200
    twice = await client.post(f"/api/fasting/{started['id']}/end", json={})
    assert twice.status_code == 409
    assert twice.json()["error"]["code"] == "FASTING_ALREADY_ENDED"


async def test_a_fast_cannot_start_in_the_future(registered_client):
    client, _ = registered_client
    future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    resp = await client.post("/api/fasting/start", json={"started_at": future})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "FASTING_IN_THE_FUTURE"


@pytest.mark.parametrize("target", [0, 0.5, 100])
async def test_the_target_must_be_between_one_and_seventy_two_hours(registered_client, target):
    client, _ = registered_client
    resp = await client.post("/api/fasting/start", json={"target_hours": target})
    assert resp.status_code == 422


async def test_a_target_over_24_hours_carries_a_warning(registered_client):
    client, _ = registered_client
    started = await _start(client, target=36)
    assert "LONG_FAST_WARNING" in started["warnings"]
    assert started["eating_window_hours"] == 0


async def test_history_and_stats_count_only_finished_fasts(registered_client):
    client, _ = registered_client
    for started_ago, duration, target in ((60, 17, 16), (40, 12, 16), (20, 16, 16)):
        window = await _start(client, hours_ago=started_ago, target=target)
        end = (datetime.now(UTC) - timedelta(hours=started_ago - duration)).isoformat()
        assert (
            await client.post(f"/api/fasting/{window['id']}/end", json={"ended_at": end})
        ).status_code == 200
    await _start(client, hours_ago=1)  # abierto: no cuenta

    history = (await client.get("/api/fasting/history")).json()
    stats = (await client.get("/api/fasting/stats", params={"days": 30})).json()

    assert len(history) == 3
    assert [round(h["elapsed_hours"]) for h in history] == [16, 12, 17]  # más reciente primero
    assert stats["fasts"] == 3
    assert stats["reached_target"] == 2
    assert stats["adherence_pct"] == pytest.approx(66.7, abs=0.1)
    assert stats["avg_hours"] == pytest.approx(15.0, abs=0.1)
    assert stats["longest_hours"] == pytest.approx(17.0, abs=0.1)


async def test_stats_are_empty_without_fasts(registered_client):
    client, _ = registered_client
    stats = (await client.get("/api/fasting/stats")).json()
    assert stats["fasts"] == 0
    assert stats["adherence_pct"] is None
    assert stats["avg_hours"] is None


async def test_a_fast_can_be_deleted(registered_client):
    client, _ = registered_client
    started = await _start(client)
    assert (await client.delete(f"/api/fasting/{started['id']}")).status_code == 204
    assert (await client.get("/api/fasting/current")).json() is None
    assert (await client.delete(f"/api/fasting/{started['id']}")).status_code == 404


async def test_fasts_are_private_to_each_user(registered_client, fresh_client):
    client, _ = registered_client
    other, _ = fresh_client
    await other.post("/api/consents", json={"kind": "health_data", "version": "v1"})
    started = await _start(client)

    assert (await other.get("/api/fasting/current")).json() is None
    assert (await other.post(f"/api/fasting/{started['id']}/end", json={})).status_code == 404
    assert (await other.delete(f"/api/fasting/{started['id']}")).status_code == 404


async def test_starting_a_fast_needs_the_health_data_consent(fresh_client):
    client, _ = fresh_client
    resp = await client.post("/api/fasting/start", json={})
    assert resp.status_code == 403
