from datetime import date

import pytest_asyncio
from sqlalchemy import text

from myfood.ai.anonymize import age_band, budget_band, build_diet_plan_payload
from myfood.db.models import Profile, UserRestriction
from myfood.db.session import AdminSessionLocal
from myfood.domain.diet_engine import CandidateFood, DayTargets

TARGETS = DayTargets(kcal=2000, protein_g=140, fat_g=60, carbs_g=200)


def test_age_band_buckets():
    today = date.today()
    assert age_band(today.replace(year=today.year - 10)) == "<18"
    assert age_band(today.replace(year=today.year - 20)) == "18-24"
    assert age_band(today.replace(year=today.year - 30)) == "25-34"
    assert age_band(today.replace(year=today.year - 40)) == "35-44"
    assert age_band(today.replace(year=today.year - 50)) == "45-54"
    assert age_band(today.replace(year=today.year - 60)) == "55-64"
    assert age_band(today.replace(year=today.year - 70)) == "65+"


def test_budget_band_buckets():
    assert budget_band(None) is None
    assert budget_band(20) == "low"
    assert budget_band(60) == "medium"
    assert budget_band(150) == "high"


@pytest_asyncio.fixture
async def profile_with_restrictions(two_users, test_food, superuser_conn):
    user_id, _ = two_users
    async with AdminSessionLocal() as session:
        profile = await session.get(Profile, user_id)
        profile.sex = "male"
        profile.birth_date = date(1990, 1, 1)
        profile.activity_level = "moderate"
        profile.goal = "lose"
        profile.diet_style = "omnivore"
        profile.max_cook_minutes = 30
        profile.budget_eur_week = 50
        session.add(
            UserRestriction(user_id=user_id, kind="allergen", allergen_code="gluten")
        )
        session.add(
            UserRestriction(user_id=user_id, kind="disliked_food", food_id=test_food)
        )
        await session.commit()
    yield user_id
    await superuser_conn.execute(
        text("DELETE FROM user_restrictions WHERE user_id = :id"), {"id": str(user_id)}
    )
    await superuser_conn.commit()


async def test_payload_never_contains_real_food_ids(profile_with_restrictions):
    user_id = profile_with_restrictions
    candidates = [
        CandidateFood(
            id="11111111-1111-1111-1111-111111111111",
            name_es="Pechuga de pollo",
            kcal_100g=165,
            protein_100g=31,
            fat_100g=3.6,
            carbs_100g=0,
            category="meat",
        )
    ]
    async with AdminSessionLocal() as session:
        profile = await session.get(Profile, user_id)
        result = await build_diet_plan_payload(
            session,
            profile=profile,
            targets=TARGETS,
            meals_per_day=4,
            candidates=candidates,
        )

    payload_str = str(result.payload)
    assert "11111111-1111-1111-1111-111111111111" not in payload_str
    assert result.alias_to_food_id == {"c1": "11111111-1111-1111-1111-111111111111"}
    assert result.payload["candidates"][0]["id"] == "c1"
    assert result.payload["candidates"][0]["name"] == "Pechuga de pollo"


async def test_payload_never_contains_identifying_data(profile_with_restrictions):
    user_id = profile_with_restrictions
    async with AdminSessionLocal() as session:
        profile = await session.get(Profile, user_id)
        result = await build_diet_plan_payload(
            session, profile=profile, targets=TARGETS, meals_per_day=4, candidates=[]
        )

    payload_str = str(result.payload)
    assert str(user_id) not in payload_str
    assert "1990" not in payload_str  # birth_date exacto nunca sale, solo age_band
    assert result.payload["context"]["age_band"] != "1990-01-01"


async def test_payload_context_and_restrictions(profile_with_restrictions):
    user_id = profile_with_restrictions
    async with AdminSessionLocal() as session:
        profile = await session.get(Profile, user_id)
        result = await build_diet_plan_payload(
            session, profile=profile, targets=TARGETS, meals_per_day=4, candidates=[]
        )

    ctx = result.payload["context"]
    assert ctx["sex"] == "male"
    assert ctx["activity_level"] == "moderate"
    assert ctx["goal"] == "lose"
    assert ctx["diet_style"] == "omnivore"
    assert ctx["max_cook_minutes"] == 30
    assert ctx["budget_band"] == "medium"
    assert ctx["meals_per_day"] == 4

    assert result.payload["restrictions"]["allergens"] == ["gluten"]
    assert result.payload["restrictions"]["disliked"] == ["Pechuga de pollo de prueba"]

    assert result.payload["targets"] == {
        "kcal": 2000,
        "protein_g": 140,
        "fat_g": 60,
        "carbs_g": 200,
    }
