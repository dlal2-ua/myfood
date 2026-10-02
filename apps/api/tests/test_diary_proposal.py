"""Lo que el chat propone apuntar en el diario (`domain/diary_proposal.py`).

Lo importante: que los números de un alimento del catálogo salgan del dato oficial y no del
modelo, que lo que el modelo estima quede marcado, y que un disparate no entre en el histórico.
"""

import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
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


# --- platos estimados enteros (migración 0026) ---------------------------------------------

MARINERA = {
    "nombre": "marinera",
    "cantidad": 2,
    "gramos": 130,
    "kcal": 260,
    "proteina_g": 8,
    "grasa_g": 9,
    "carbos_g": 38,
    "componentes": [
        {"nombre": "rosquilla", "gramos": 60, "kcal": 160},
        {"nombre": "ensaladilla rusa", "gramos": 60, "kcal": 90},
        {"nombre": "anchoa", "gramos": 10, "kcal": 10},
    ],
}


@pytest_asyncio.fixture
async def no_saved_dishes_left_behind(superuser_conn):
    yield
    await superuser_conn.execute(
        text(
            "DELETE FROM food_log WHERE food_id IN "
            "(SELECT id FROM foods WHERE source = 'ai_estimate')"
        )
    )
    await superuser_conn.execute(text("DELETE FROM foods WHERE source = 'ai_estimate'"))
    await superuser_conn.commit()


async def _dish_payload(*dishes: dict, meal_type: str = "morning_snack") -> dict:
    async with AdminSessionLocal() as session:
        return await diary_proposal.build_payload(
            session,
            {"date": date.today().isoformat(), "meal_type": meal_type, "items": list(dishes)},
            alias_to_candidate={},
            today=date.today(),
        )


async def test_a_dish_is_one_line_with_its_breakdown_and_the_values_are_per_unit():
    """«Dos marineras» es una línea de 520 kcal con su desglose, no seis ingredientes."""
    payload = await _dish_payload(MARINERA)

    (item,) = payload["items"]
    assert item["name"] == "Marinera"
    assert item["quantity"] == 2
    assert (item["grams"], item["kcal"]) == (260, 520)
    assert (item["protein_g"], item["fat_g"], item["carbs_g"]) == (16, 18, 76)
    assert item["components"] == [
        {"name": "rosquilla", "grams": 120, "kcal": 320},
        {"name": "ensaladilla rusa", "grams": 120, "kcal": 180},
        {"name": "anchoa", "grams": 20, "kcal": 20},
    ]
    assert item["estimated"] is True and item["food_id"] is None
    assert item["from_catalog"] is False
    assert payload["has_estimates"] is True


async def test_the_breakdown_decides_the_calories_of_the_dish():
    """Lo que se enseña debajo tiene que sumar el total: si el modelo dice 520 y sus partes
    suman 490, valen las partes."""
    payload = await _dish_payload(
        {
            "nombre": "bocadillo de pastrami",
            "gramos": 200,
            "kcal": 520,
            "componentes": [
                {"nombre": "pan de cristal", "gramos": 90, "kcal": 230},
                {"nombre": "pastrami", "gramos": 60, "kcal": 110},
                {"nombre": "mayonesa", "gramos": 20, "kcal": 140},
                {"nombre": "rúcula"},  # sin cifras: no se puede sumar, manda el plato
            ],
        },
        {
            "nombre": "tostada con tomate",
            "gramos": 80,
            "kcal": 180,
            "componentes": [
                {"nombre": "pan", "gramos": 60, "kcal": 150},
                {"nombre": "tomate", "gramos": 20, "kcal": 5},
            ],
        },
    )
    bocadillo, tostada = payload["items"]
    assert bocadillo["kcal"] == 520
    assert tostada["kcal"] == 155


async def test_each_dish_can_go_to_its_own_meal():
    payload = await _dish_payload(
        {"nombre": "café con leche", "gramos": 200, "kcal": 70, "comida": "breakfast"},
        {"nombre": "caña", "gramos": 200, "kcal": 90},
        {"nombre": "sopa", "gramos": 300, "kcal": 120, "comida": "merienda-cena"},
        meal_type="lunch",
    )
    assert [i["meal_type"] for i in payload["items"]] == ["breakfast", "lunch", "lunch"]


@pytest.mark.parametrize(
    ("dish", "code"),
    [
        ({"nombre": "caña", "gramos": 200, "kcal": 9000}, "IMPLAUSIBLE_ESTIMATE"),
        ({"nombre": "caña", "gramos": 0, "kcal": 90}, "IMPLAUSIBLE_ESTIMATE"),
        ({"nombre": "paella", "gramos": 400, "kcal": 600, "cantidad": 20}, "IMPLAUSIBLE_ESTIMATE"),
        ({"nombre": "caña"}, "INVALID_ESTIMATE"),  # ni guardado ni con cifras
        ({"nombre": "  ", "gramos": 200, "kcal": 90}, "MISSING_NAME"),
    ],
)
async def test_an_impossible_dish_never_reaches_the_diary(dish, code):
    with pytest.raises(AppError) as exc:
        await _dish_payload(dish)
    assert exc.value.code == code


async def test_a_macro_cannot_weigh_more_than_the_dish():
    payload = await _dish_payload(
        {"nombre": "caña", "gramos": 200, "kcal": 90, "proteina_g": 900, "grasa_g": -4}
    )
    (item,) = payload["items"]
    assert item["protein_g"] == 200 and item["fat_g"] == 0


def test_the_summary_reads_like_what_the_user_asked_for():
    """Total aproximado y una línea por plato, con el bocadillo como un conjunto."""
    text_out = diary_proposal.summary_text(
        {
            "has_estimates": True,
            "totals": {"kcal": 870.4},
            "items": [
                {
                    "name": "Marinera",
                    "kcal": 520,
                    "quantity": 2,
                    "estimated": True,
                    "components": [{"name": "rosquilla"}, {"name": "ensaladilla rusa"}],
                },
                {"name": "Caña de cerveza", "kcal": 90, "estimated": True, "components": []},
                {"name": "Yogur natural Danone", "kcal": 260.4, "estimated": False},
            ],
        }
    )
    assert text_out == (
        "Aprox. 870 kcal en total:\n"
        "• Marinera ×2: aprox. 520 kcal (rosquilla, ensaladilla rusa)\n"
        "• Caña de cerveza: aprox. 90 kcal\n"
        # El dato de catálogo no lleva «aprox.»: solo lo estimado se presenta como estimación.
        "• Yogur natural Danone: 260 kcal\n"
        "Es una estimación orientativa, no una medición."
    )
    assert diary_proposal.summary_text({"items": []}) is None


async def test_saving_a_dish_on_approval_adds_it_to_the_catalog_and_reuses_it_next_time(
    registered_client, superuser_conn, no_saved_dishes_left_behind
):
    """El ciclo entero: se estima, se acepta marcando «guardar en el catálogo», y la siguiente
    vez que se nombra salen los números guardados aunque el modelo diga otros."""
    client, user_id = registered_client
    payload = await _dish_payload(MARINERA, {"nombre": "caña", "gramos": 200, "kcal": 90})
    saved_ids: list = []
    async with AdminSessionLocal() as session:
        written = await diary_proposal.materialize(
            session, user_id, payload, save_to_catalog=[0], saved_food_ids=saved_ids
        )
        await session.commit()
    assert written == 2 and len(saved_ids) == 1

    rows = (
        await superuser_conn.execute(
            text(
                "SELECT food_id, custom_name, entry_source, kcal, components FROM food_log "
                "WHERE user_id = :u ORDER BY kcal DESC"
            ),
            {"u": str(user_id)},
        )
    ).all()
    marinera, cana = rows
    # La guardada apunta a su ficha; la otra sigue identificándose por su nombre.
    assert marinera.food_id == saved_ids[0] and marinera.custom_name is None
    assert cana.food_id is None and cana.custom_name == "Caña"
    # Guardada o no, sigue siendo una estimación y se enseña como tal.
    assert {marinera.entry_source, cana.entry_source} == {"ai_estimate"}
    assert [c["name"] for c in marinera.components] == ["rosquilla", "ensaladilla rusa", "anchoa"]

    # La ficha del catálogo guarda UNA ración (se comieron dos) y su desglose.
    detail = (await client.get(f"/api/foods/{saved_ids[0]}")).json()
    assert detail["source"] == "ai_estimate"
    assert detail["serving_size_g"] == 130
    assert detail["kcal_100g"] == 200  # 260 kcal en 130 g
    assert [c["name"] for c in detail["components"]] == ["rosquilla", "ensaladilla rusa", "anchoa"]
    assert detail["components"][0]["kcal"] == 160

    # La próxima marinera: el modelo dice 999 kcal, valen las 260 guardadas.
    again = await _dish_payload({"nombre": "Marineras", "cantidad": 1, "gramos": 50, "kcal": 999})
    (item,) = again["items"]
    assert item["from_catalog"] is True
    assert item["food_id"] == str(saved_ids[0])
    assert (item["grams"], item["kcal"]) == (130, 260)
    assert item["estimated"] is True
