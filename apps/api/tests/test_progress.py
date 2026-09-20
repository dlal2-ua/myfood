"""Resumen de progreso (`/progress/summary`, `/progress/tdee`) y sus cálculos puros."""

from datetime import date, timedelta

import pytest

from myfood.domain import progress as calc


def _d(offset: int) -> date:
    return date(2026, 1, 1) + timedelta(days=offset)


# --- cálculos puros ------------------------------------------------------------------------------


def test_the_moving_average_covers_the_seven_calendar_days_ending_each_day():
    points = [(_d(0), 80.0), (_d(1), 79.0), (_d(6), 78.0), (_d(7), 77.0)]
    averaged = {d: ma for d, _w, ma in calc.moving_average(points)}
    assert averaged[_d(0)] == pytest.approx(80.0)
    assert averaged[_d(1)] == pytest.approx(79.5)
    assert averaged[_d(6)] == pytest.approx((80 + 79 + 78) / 3)
    # el día 0 ya no cuenta en la ventana que termina el día 7 (días 1..7)
    assert averaged[_d(7)] == pytest.approx((79 + 78 + 77) / 3)


def test_a_single_weigh_in_is_its_own_average():
    assert calc.moving_average([(_d(0), 70.0)]) == [(_d(0), 70.0, 70.0)]


def test_the_trend_of_a_steady_loss_is_its_weekly_slope():
    series = [(_d(i), 80 - 0.1 * i) for i in range(30)]
    assert calc.trend_kg_per_week(series) == pytest.approx(-0.7, abs=1e-6)


def test_the_trend_of_a_flat_series_is_zero():
    assert calc.trend_kg_per_week([(_d(i), 75.0) for i in range(14)]) == pytest.approx(0.0)


@pytest.mark.parametrize(
    "series",
    [[], [(_d(0), 80.0)], [(_d(0), 80.0), (_d(3), 79.0)]],
)
def test_there_is_no_trend_without_a_week_of_data(series):
    assert calc.trend_kg_per_week(series) is None


# --- endpoints -----------------------------------------------------------------------------------


async def _weigh(client, offset_days_ago: int, kg: float):
    day = (date.today() - timedelta(days=offset_days_ago)).isoformat()
    resp = await client.post("/api/measurements", json={"measured_on": day, "weight_kg": kg})
    assert resp.status_code in (200, 201)


async def test_the_summary_of_a_user_without_data_is_empty(registered_client):
    client, _ = registered_client
    resp = await client.get("/api/progress/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["period_days"] == 30
    assert body["weight"]["points"] == []
    assert body["weight"]["trend_kg_per_week"] is None
    assert body["intake"]["logging_days"] == 0
    assert body["intake"]["adherence_pct"] == 0
    assert body["intake"]["avg_kcal"] is None
    assert body["water_avg_ml"] is None


async def test_the_summary_reports_weight_with_its_moving_average_and_trend(registered_client):
    client, _ = registered_client
    for ago in range(20, -1, -1):
        await _weigh(client, ago, round(80 - 0.1 * (20 - ago), 1))

    body = (await client.get("/api/progress/summary", params={"period": "30d"})).json()

    weight = body["weight"]
    assert len(weight["points"]) == 21
    assert weight["start_kg"] == 80.0
    assert weight["end_kg"] == 78.0
    assert weight["change_kg"] == -2.0
    assert weight["trend_kg_per_week"] == pytest.approx(
        -0.7, abs=0.12
    )  # el arranque de la media móvil la suaviza
    last = weight["points"][-1]
    assert last["weight_kg"] == 78.0
    # media de las 7 últimas pesadas: 78.6 ... 78.0
    assert last["ma7_kg"] == pytest.approx(78.3, abs=0.01)


async def test_the_period_limits_the_weights_shown(registered_client):
    client, _ = registered_client
    await _weigh(client, 40, 90)
    await _weigh(client, 3, 85)
    week = (await client.get("/api/progress/summary", params={"period": "7d"})).json()
    quarter = (await client.get("/api/progress/summary", params={"period": "90d"})).json()
    assert [p["weight_kg"] for p in week["weight"]["points"]] == [85.0]
    assert [p["weight_kg"] for p in quarter["weight"]["points"]] == [90.0, 85.0]


async def test_adherence_counts_days_with_food_logged_not_results(registered_client, test_food):
    client, _ = registered_client
    for ago in (0, 1, 2):
        day = (date.today() - timedelta(days=ago)).isoformat()
        await client.post(
            "/api/log/food",
            json={"log_date": day, "meal_type": "lunch", "food_id": str(test_food), "grams": 100},
        )
        await client.post(
            "/api/log/food",
            json={"log_date": day, "meal_type": "dinner", "food_id": str(test_food), "grams": 100},
        )

    intake = (await client.get("/api/progress/summary", params={"period": "7d"})).json()["intake"]

    assert intake["logging_days"] == 3
    assert intake["adherence_pct"] == pytest.approx(3 / 7 * 100, abs=0.1)
    assert intake["avg_kcal"] == 330.0  # 2 x 100 g de pollo (165 kcal) por día
    assert intake["avg_protein_g"] == 62.0
    assert len(intake["daily"]) == 3


async def test_the_summary_includes_the_current_target_when_the_profile_allows_it(
    registered_client,
):
    client, _ = registered_client
    await client.put(
        "/api/profile", json={"sex": "male", "birth_date": "1995-01-01", "height_cm": 180}
    )
    await _weigh(client, 0, 80)
    target = (await client.get("/api/calc/targets")).json()["kcal"]
    intake = (await client.get("/api/progress/summary")).json()["intake"]
    assert intake["target_kcal"] == target


async def test_the_water_average_only_counts_days_with_water(registered_client):
    client, _ = registered_client
    for ago, ml in ((0, 500), (0, 500), (1, 1500)):
        day = (date.today() - timedelta(days=ago)).isoformat()
        await client.post("/api/water/log", json={"log_date": day, "ml": ml})
    body = (await client.get("/api/progress/summary", params={"period": "7d"})).json()
    assert body["water_avg_ml"] == pytest.approx(1250.0)


@pytest.mark.parametrize("period", ["1d", "10d", "30", "year"])
async def test_an_unsupported_period_is_rejected(registered_client, period):
    client, _ = registered_client
    assert (await client.get("/api/progress/summary", params={"period": period})).status_code == 422


async def test_the_summary_is_private_to_each_user(registered_client, fresh_client):
    client, _ = registered_client
    other, _ = fresh_client
    await _weigh(client, 0, 70)
    assert (await other.get("/api/progress/summary")).json()["weight"]["points"] == []


async def test_the_tdee_history_is_empty_without_weights_and_unreliable_at_first(registered_client):
    client, _ = registered_client
    empty = (await client.get("/api/progress/tdee")).json()
    assert empty == {"current": None, "source": "formula", "history": []}

    await _weigh(client, 0, 80)
    started = (await client.get("/api/progress/tdee")).json()
    assert started["source"] == "formula"
    assert started["current"]["is_reliable"] is False
    assert len(started["history"]) == 1


async def test_the_tdee_history_requires_a_session():
    from httpx import ASGITransport, AsyncClient

    from myfood.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as anon:
        assert (await anon.get("/api/progress/tdee")).status_code == 401
        assert (await anon.get("/api/progress/summary")).status_code == 401
