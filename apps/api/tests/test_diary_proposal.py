"""Lo que el chat propone apuntar en el diario (`domain/diary_proposal.py`).

Lo importante: que los números de un alimento del catálogo salgan del dato oficial y no del
modelo, que lo que el modelo estima quede marcado, y que un disparate no entre en el histórico.
"""

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from myfood.db.session import AdminSessionLocal
from myfood.domain import diary_proposal
from myfood.domain.diet_engine import CandidateFood
from myfood.errors import AppError

pytestmark = pytest.mark.asyncio

TODAY = date(2026, 9, 22)


def candidate(food_id) -> CandidateFood:
    return CandidateFood(
        id=str(food_id),
        name_es="Pechuga de pollo de prueba",
        kcal_100g=165,
        protein_100g=31,
        fat_100g=3.6,
        carbs_100g=0,
        category=None,
    )


def test_a_future_date_is_refused():
    """El chat apunta lo que YA se ha comido (decisión del usuario)."""
    with pytest.raises(AppError) as exc:
        diary_proposal.validate_date((TODAY + timedelta(days=1)).isoformat(), today=TODAY)
    assert exc.value.code == "FUTURE_DATE"


def test_today_and_past_days_are_fine():
    assert diary_proposal.validate_date(TODAY.isoformat(), today=TODAY) == TODAY
    yesterday = TODAY - timedelta(days=1)
    assert diary_proposal.validate_date(yesterday.isoformat(), today=TODAY) == yesterday


def test_a_date_that_makes_no_sense_is_refused():
    with pytest.raises(AppError) as exc:
        diary_proposal.validate_date("el lunes", today=TODAY)
    assert exc.value.code == "INVALID_DATE"


async def test_a_catalog_food_takes_its_numbers_from_the_catalog(test_food):
    """Ni las calorías ni los gramos los pone el modelo: solo dice «una pechuga»."""
    async with AdminSessionLocal() as session:
        payload = await diary_proposal.build_payload(
            session,
            {
                "date": date.today().isoformat(),
                "meal_type": "lunch",
                "request": "una pechuga de pollo",
                "items": [{"alias": "c1", "quantity_text": "200 g"}],
            },
            alias_to_candidate={"c1": candidate(test_food)},
            today=date.today(),
        )
    item = payload["items"][0]
    assert item["estimated"] is False
    assert item["grams"] == 200
    assert item["kcal"] == 330  # 165 kcal/100 g × 200 g
    assert item["protein_g"] == 62
    assert payload["totals"]["kcal"] == 330
    assert payload["has_estimates"] is False
    assert payload["request"] == "una pechuga de pollo"


async def test_an_ingredient_outside_the_catalog_is_marked_as_an_estimate(test_food):
    async with AdminSessionLocal() as session:
        payload = await diary_proposal.build_payload(
            session,
            {
                "date": date.today().isoformat(),
                "meal_type": "morning_snack",
                "request": "tostada de tomate con queso manchego",
                "items": [
                    {"alias": "c1", "quantity_text": "30 g"},
                    {
                        "name": "Queso manchego semicurado",
                        "grams": 25,
                        "kcal_100g": 380,
                        "protein_100g": 25,
                        "fat_100g": 31,
                        "carbs_100g": 1,
                    },
                ],
            },
            alias_to_candidate={"c1": candidate(test_food)},
            today=date.today(),
        )
    catalogo, estimado = payload["items"]
    assert catalogo["estimated"] is False
    assert estimado["estimated"] is True
    assert estimado["name"] == "Queso manchego semicurado"
    assert estimado["kcal"] == 95  # 380 × 25 / 100
    assert estimado["food_id"] is None
    assert payload["has_estimates"] is True
    assert payload["totals"]["kcal"] == catalogo["kcal"] + estimado["kcal"]


async def test_an_implausible_estimate_never_reaches_the_diary():
    """Un error de interpretación del modelo no puede meter 5000 kcal/100 g en el histórico."""
    async with AdminSessionLocal() as session:
        for bad in [
            {"name": "X", "grams": 100, "kcal_100g": 5000},
            {"name": "X", "grams": 99999, "kcal_100g": 100},
            {"name": "X", "grams": 0, "kcal_100g": 100},
        ]:
            with pytest.raises(AppError) as exc:
                await diary_proposal.build_payload(
                    session,
                    {"date": date.today().isoformat(), "meal_type": "lunch", "items": [bad]},
                    alias_to_candidate={},
                    today=date.today(),
                )
            assert exc.value.code == "IMPLAUSIBLE_ESTIMATE"


async def test_an_estimate_without_a_name_is_refused():
    async with AdminSessionLocal() as session:
        with pytest.raises(AppError) as exc:
            await diary_proposal.build_payload(
                session,
                {
                    "date": date.today().isoformat(),
                    "meal_type": "lunch",
                    "items": [{"grams": 50, "kcal_100g": 200}],
                },
                alias_to_candidate={},
                today=date.today(),
            )
        assert exc.value.code == "MISSING_NAME"


async def test_a_meal_that_does_not_exist_is_refused():
    async with AdminSessionLocal() as session:
        with pytest.raises(AppError) as exc:
            await diary_proposal.build_payload(
                session,
                {"date": date.today().isoformat(), "meal_type": "brunch", "items": [{}]},
                alias_to_candidate={},
                today=date.today(),
            )
        assert exc.value.code == "INVALID_MEAL_TYPE"


async def test_approving_writes_exactly_the_numbers_that_were_accepted(
    registered_client, superuser_conn, test_food
):
    """Se guarda el snapshot que el usuario vio y aceptó, no un recálculo posterior."""
    client, user_id = registered_client
    async with AdminSessionLocal() as session:
        payload = await diary_proposal.build_payload(
            session,
            {
                "date": date.today().isoformat(),
                "meal_type": "dinner",
                "items": [
                    {"alias": "c1", "quantity_text": "150 g"},
                    {"name": "Pan de pueblo", "grams": 40, "kcal_100g": 260, "protein_100g": 8},
                ],
            },
            alias_to_candidate={"c1": candidate(test_food)},
            today=date.today(),
        )
        written = await diary_proposal.materialize(session, user_id, payload)
        await session.commit()
    assert written == 2

    day = (await client.get(f"/api/log?date={date.today().isoformat()}")).json()
    assert len(day["food"]) == 2
    assert round(day["totals"]["kcal"]) == round(payload["totals"]["kcal"])

    sources = (
        await superuser_conn.execute(
            text(
                "SELECT entry_source, custom_name FROM food_log "
                "WHERE user_id = :u ORDER BY entry_source"
            ),
            {"u": str(user_id)},
        )
    ).all()
    assert [r.entry_source for r in sources] == ["ai_estimate", "chat"]
    # La línea estimada guarda su nombre: sin alimento del catálogo no habría cómo llamarla.
    assert sources[0].custom_name == "Pan de pueblo"
    assert sources[1].custom_name is None


async def test_reading_a_day_gives_the_identifiers_needed_to_correct_it(
    registered_client, test_food
):
    client, user_id = registered_client
    await client.post(
        "/api/log/food",
        json={
            "log_date": date.today().isoformat(),
            "meal_type": "lunch",
            "food_id": str(test_food),
            "grams": 100,
        },
    )
    async with AdminSessionLocal() as session:
        entries = await diary_proposal.read_day(session, user_id, date.today())
    assert len(entries) == 1
    assert uuid.UUID(entries[0]["entry_id"])
    assert entries[0]["name"] == "Pechuga de pollo de prueba"
    assert entries[0]["estimated"] is False
