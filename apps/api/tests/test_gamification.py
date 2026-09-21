"""GET /gamification/summary — cableado del router (la lógica pura ya está
probada en test_gamification_domain.py)."""

from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.asyncio


async def test_summary_with_no_activity(registered_client):
    client, _ = registered_client
    resp = await client.get("/api/gamification/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_streak"] == 0
    assert body["longest_streak"] == 0
    assert len(body["heatmap"]) == 365
    assert all(day["count"] == 0 for day in body["heatmap"])
    assert all(not a["earned"] for a in body["achievements"])


async def test_summary_reflects_real_food_log_streak(registered_client, test_food):
    client, _ = registered_client
    today = date.today()
    for offset in range(3):
        day = (today - timedelta(days=offset)).isoformat()
        resp = await client.post(
            "/api/log/food",
            json={
                "log_date": day,
                "meal_type": "lunch",
                "food_id": str(test_food),
                "grams": 100,
            },
        )
        assert resp.status_code == 201

    body = (await client.get("/api/gamification/summary")).json()
    assert body["current_streak"] == 3
    assert body["longest_streak"] == 3

    today_entry = next(d for d in body["heatmap"] if d["date"] == today.isoformat())
    assert today_entry["count"] == 1


async def test_summary_achievement_unlocks_with_ten_recipes(registered_client):
    client, _ = registered_client
    for i in range(10):
        resp = await client.post("/api/recipes", json={"name": f"Receta {i}", "servings": 1})
        assert resp.status_code == 201

    body = (await client.get("/api/gamification/summary")).json()
    recipes_achievement = next(a for a in body["achievements"] if a["key"] == "recipes_10")
    assert recipes_achievement["earned"] is True
    assert recipes_achievement["progress"] == 10


async def test_summary_does_not_leak_other_users_activity(
    registered_client, superuser_conn, test_food
):
    client, _ = registered_client
    await client.post(
        "/api/log/food",
        json={
            "log_date": date.today().isoformat(),
            "meal_type": "lunch",
            "food_id": str(test_food),
            "grams": 100,
        },
    )

    import uuid

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text

    from myfood.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as other_client:
        email = f"other-{uuid.uuid4()}@test.myfood"
        other_resp = await other_client.post(
            "/api/auth/register",
            json={"email": email, "password": "correcthorse123", "display_name": "Other"},
        )
        other_id = other_resp.json()["id"]
        body = (await other_client.get("/api/gamification/summary")).json()
        assert body["current_streak"] == 0

    await superuser_conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": other_id})
    await superuser_conn.commit()


async def test_achievement_is_only_new_the_first_time(registered_client, test_food):
    """`newly_earned` es lo que la pantalla celebra: debe salir una vez y no en cada
    recarga, o el usuario vería la misma fiesta cada vez que entra en Progreso."""
    client, _ = registered_client
    resp = await client.post(
        "/api/log/food",
        json={
            "log_date": date.today().isoformat(),
            "meal_type": "lunch",
            "food_id": str(test_food),
            "grams": 100,
        },
    )
    assert resp.status_code == 201

    first = (await client.get("/api/gamification/summary")).json()
    assert "first_log" in first["newly_earned"]
    earned = next(a for a in first["achievements"] if a["key"] == "first_log")
    assert earned["earned"] is True
    assert earned["earned_on"] == date.today().isoformat()

    second = (await client.get("/api/gamification/summary")).json()
    assert second["newly_earned"] == []
    still = next(a for a in second["achievements"] if a["key"] == "first_log")
    assert still["earned_on"] == date.today().isoformat()


async def test_every_achievement_carries_its_badge(registered_client):
    client, _ = registered_client
    body = (await client.get("/api/gamification/summary")).json()
    for a in body["achievements"]:
        assert a["icon"] and a["tier"] and a["family"]
        assert a["earned_on"] is None


async def test_complete_day_needs_three_meals(registered_client, test_food):
    """Un día «completo» son las tres comidas principales, no tres registros sueltos."""
    client, _ = registered_client
    today = date.today().isoformat()
    for meal in ("lunch", "lunch", "lunch"):
        await client.post(
            "/api/log/food",
            json={"log_date": today, "meal_type": meal, "food_id": str(test_food), "grams": 100},
        )
    body = (await client.get("/api/gamification/summary")).json()
    assert next(a for a in body["achievements"] if a["key"] == "complete_days_10")["progress"] == 0

    for meal in ("breakfast", "dinner"):
        await client.post(
            "/api/log/food",
            json={"log_date": today, "meal_type": meal, "food_id": str(test_food), "grams": 100},
        )
    body = (await client.get("/api/gamification/summary")).json()
    assert next(a for a in body["achievements"] if a["key"] == "complete_days_10")["progress"] == 1
