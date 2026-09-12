import uuid

import pytest_asyncio
from sqlalchemy import text

from myfood.ai.validator import validate_day_totals, validate_structure
from myfood.db.models import UserRestriction
from myfood.db.session import AdminSessionLocal
from myfood.domain.diet_engine import DayTargets

TARGETS = DayTargets(kcal=2000, protein_g=140, fat_g=60, carbs_g=200)


# --- validate_day_totals (pura, sin BD) --------------------------------------


def test_totals_within_tolerance_has_no_errors():
    actual = DayTargets(kcal=2050, protein_g=145, fat_g=65, carbs_g=210)
    errors = validate_day_totals(actual, TARGETS, safety_floor_kcal=1500, min_fat_g=40)
    assert errors == []


def test_kcal_out_of_range_is_flagged():
    actual = DayTargets(kcal=2500, protein_g=145, fat_g=65, carbs_g=210)  # +25%
    errors = validate_day_totals(actual, TARGETS, safety_floor_kcal=1500, min_fat_g=40)
    assert {e.code for e in errors} == {"KCAL_OUT_OF_RANGE"}


def test_protein_too_low_is_flagged():
    actual = DayTargets(kcal=2000, protein_g=100, fat_g=65, carbs_g=210)  # < 90% de 140
    errors = validate_day_totals(actual, TARGETS, safety_floor_kcal=1500, min_fat_g=40)
    assert "PROTEIN_TOO_LOW" in {e.code for e in errors}


def test_fat_below_hormonal_minimum_is_flagged():
    actual = DayTargets(kcal=2000, protein_g=145, fat_g=20, carbs_g=210)
    errors = validate_day_totals(actual, TARGETS, safety_floor_kcal=1500, min_fat_g=40)
    assert "FAT_BELOW_HORMONAL_MINIMUM" in {e.code for e in errors}


def test_below_safety_floor_is_flagged_even_when_matching_target():
    low_targets = DayTargets(kcal=1000, protein_g=140, fat_g=60, carbs_g=200)
    actual = DayTargets(kcal=1000, protein_g=145, fat_g=65, carbs_g=210)
    errors = validate_day_totals(actual, low_targets, safety_floor_kcal=1500, min_fat_g=40)
    assert "BELOW_SAFETY_FLOOR" in {e.code for e in errors}


# --- validate_structure (async, re-verifica contra la BD real) --------------


@pytest_asyncio.fixture
async def restricted_food(two_users, test_food, superuser_conn):
    user_id, _ = two_users
    async with AdminSessionLocal() as session:
        session.add(UserRestriction(user_id=user_id, kind="disliked_food", food_id=test_food))
        await session.commit()
    yield user_id, test_food
    await superuser_conn.execute(
        text("DELETE FROM user_restrictions WHERE user_id = :id"), {"id": str(user_id)}
    )
    await superuser_conn.commit()


async def test_structure_ok_resolves_aliases_to_food_ids(two_users):
    user_id, _ = two_users
    alias_to_food_id = {"c1": "11111111-1111-1111-1111-111111111111"}
    plan_args = {
        "days": [
            {
                "day_index": 0,
                "meals": [
                    {"meal_type": "lunch", "items": [{"alias": "c1", "approx_portion": "medium"}]}
                ],
            }
        ]
    }
    async with AdminSessionLocal() as session:
        errors, resolved = await validate_structure(
            session,
            plan_args,
            alias_to_food_id=alias_to_food_id,
            user_id=user_id,
            expected_num_days=1,
            expected_meal_types=["lunch"],
        )
    assert errors == []
    assert resolved == {0: {"lunch": ["11111111-1111-1111-1111-111111111111"]}}


async def test_structure_flags_unknown_alias():
    plan_args = {
        "days": [
            {
                "day_index": 0,
                "meals": [
                    {
                        "meal_type": "lunch",
                        "items": [{"alias": "ghost", "approx_portion": "medium"}],
                    }
                ],
            }
        ]
    }
    async with AdminSessionLocal() as session:
        errors, _ = await validate_structure(
            session,
            plan_args,
            alias_to_food_id={},
            user_id=uuid.uuid4(),
            expected_num_days=1,
            expected_meal_types=["lunch"],
        )
    assert "UNKNOWN_ALIAS" in {e.code for e in errors}


async def test_structure_flags_wrong_day_count():
    async with AdminSessionLocal() as session:
        errors, _ = await validate_structure(
            session,
            {"days": []},
            alias_to_food_id={},
            user_id=uuid.uuid4(),
            expected_num_days=2,
            expected_meal_types=["lunch"],
        )
    assert "STRUCTURE_MISMATCH" in {e.code for e in errors}


async def test_structure_flags_unknown_meal_type():
    plan_args = {"days": [{"day_index": 0, "meals": [{"meal_type": "brunch", "items": []}]}]}
    async with AdminSessionLocal() as session:
        errors, _ = await validate_structure(
            session,
            plan_args,
            alias_to_food_id={},
            user_id=uuid.uuid4(),
            expected_num_days=1,
            expected_meal_types=["lunch"],
        )
    assert "UNKNOWN_MEAL_TYPE" in {e.code for e in errors}


async def test_structure_rejects_restricted_food_even_if_it_was_aliased(restricted_food):
    """Defensa en profundidad real: aunque `alias_to_food_id` mapee a un
    alimento restringido (simula un bug futuro en la selección de
    candidatos), el validador lo detecta re-consultando la BD, en vez de
    fiarse ciegamente de que el mapa de alias ya viene limpio."""
    user_id, food_id = restricted_food
    alias_to_food_id = {"c1": str(food_id)}
    plan_args = {
        "days": [
            {
                "day_index": 0,
                "meals": [
                    {"meal_type": "lunch", "items": [{"alias": "c1", "approx_portion": "medium"}]}
                ],
            }
        ]
    }
    async with AdminSessionLocal() as session:
        errors, _ = await validate_structure(
            session,
            plan_args,
            alias_to_food_id=alias_to_food_id,
            user_id=user_id,
            expected_num_days=1,
            expected_meal_types=["lunch"],
        )
    assert "RESTRICTED_FOOD_SELECTED" in {e.code for e in errors}
