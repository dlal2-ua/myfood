"""Platos estimados guardados en el catálogo (`domain/estimated_dishes.py`).

Lo que importa: que reconocer un plato guardado en una frase sea estricto (cualquier cosa que
no se entienda va al modelo, nunca se apunta a ojo) y que guardar dos veces no deje dos platos.
"""

import pytest
import pytest_asyncio
from sqlalchemy import text

from myfood.db.session import AdminSessionLocal
from myfood.domain import estimated_dishes
from myfood.domain.estimated_dishes import SavedDish


def dish(name: str, kcal: float = 260) -> SavedDish:
    return SavedDish(
        food_id="00000000-0000-0000-0000-000000000001",
        name=name,
        norm=estimated_dishes.normalize_name(name),
        grams=130,
        kcal=kcal,
        protein_g=8,
        fat_g=9,
        carbs_g=38,
    )


def saved(*names: str) -> dict[str, SavedDish]:
    return {d.norm: d for d in (dish(name) for name in names)}


def test_the_same_dish_is_recognised_however_it_is_written():
    normalize = estimated_dishes.normalize_name
    assert normalize("Marinera") == normalize("una marinera") == normalize("dos MARINERAS")
    assert normalize("Caña de cerveza") == normalize("caña de cerveza")
    assert normalize("Rúcula") == normalize("rucula")
    assert normalize("marinera") != normalize("marinero")


def test_a_sentence_made_only_of_saved_dishes_needs_no_model():
    catalog = saved("Marinera", "Caña de cerveza")
    resolved = estimated_dishes.resolve_without_model(
        "Hoy a media mañana me he tomado dos marineras y una caña de cerveza", catalog
    )
    assert [(count, d.name) for count, d in resolved] == [
        (2, "Marinera"),
        (1, "Caña de cerveza"),
    ]


def test_half_a_dish_and_a_number_are_understood():
    catalog = saved("Marinera")
    assert estimated_dishes.resolve_without_model("media marinera", catalog)[0][0] == 0.5
    assert estimated_dishes.resolve_without_model("3 marineras", catalog)[0][0] == 3
    # «media mañana» no cuenta marineras.
    assert estimated_dishes.resolve_without_model("a media mañana una marinera", catalog) == [
        (1, catalog["marinera"])
    ]


@pytest.mark.parametrize(
    "sentence",
    [
        "una marinera y un pincho de tortilla",  # hay algo que no está guardado
        "espaguetis con salsa marinera",  # el nombre aparece, pero no es el plato
        "un café con leche",  # nada guardado
        "",
    ],
)
def test_anything_not_understood_is_left_to_the_model(sentence):
    assert estimated_dishes.resolve_without_model(sentence, saved("Marinera")) is None


def test_the_longest_saved_name_wins():
    catalog = saved("Bocadillo", "Bocadillo de pastrami con rúcula")
    resolved = estimated_dishes.resolve_without_model(
        "un bocadillo de pastrami con rúcula", catalog
    )
    assert [d.name for _, d in resolved] == ["Bocadillo de pastrami con rúcula"]


def test_saved_dishes_named_in_a_message_are_found_for_the_hint():
    catalog = saved("Marinera", "Caña de cerveza")
    found = estimated_dishes.mentioned("me he comido una marinera y un pincho", catalog)
    assert [d.name for d in found] == ["Marinera"]


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        ("a media mañana una marinera", "morning_snack"),
        ("he desayunado una marinera", "breakfast"),
        ("para cenar, una marinera", "dinner"),
        ("de merienda una marinera", "afternoon_snack"),
        ("una marinera", None),
        # «Almuerzo» es la comida en media España y el bocado de media mañana en la otra.
        ("de almuerzo una marinera", None),
        # Dos comidas distintas en la misma frase: no se adivina cuál.
        ("he desayunado una marinera y he cenado otra", None),
    ],
)
def test_the_meal_is_only_taken_from_the_text_when_it_is_unambiguous(sentence, expected):
    assert estimated_dishes.detect_meal_type(sentence) == expected


# --- con base de datos -------------------------------------------------------------------


@pytest_asyncio.fixture(autouse=True)
async def no_saved_dishes_left_behind(superuser_conn):
    yield
    await superuser_conn.execute(text("DELETE FROM foods WHERE source = 'ai_estimate'"))
    await superuser_conn.commit()


ITEM = {
    "name": "Marinera",
    "quantity": 2,
    # Totales de las DOS que se comieron: lo que se guarda es una ración.
    "grams": 260,
    "kcal": 520,
    "protein_g": 16,
    "fat_g": 18,
    "carbs_g": 76,
    "components": [
        {"name": "rosquilla", "grams": 120, "kcal": 320},
        {"name": "ensaladilla rusa", "grams": 120, "kcal": 180},
        {"name": "anchoa", "grams": 20, "kcal": 20},
    ],
}


async def test_saving_a_dish_stores_one_serving_with_its_breakdown(two_users, superuser_conn):
    user_id, _ = two_users
    async with AdminSessionLocal() as session:
        food_id = await estimated_dishes.save_dish(session, user_id, ITEM)
        await session.commit()
        catalog = await estimated_dishes.load_saved(session)

    marinera = catalog["marinera"]
    assert marinera.food_id == str(food_id)
    assert (marinera.grams, round(marinera.kcal)) == (130, 260)
    assert round(marinera.protein_g) == 8
    assert [c["name"] for c in marinera.components] == ["rosquilla", "ensaladilla rusa", "anchoa"]
    assert marinera.components[0] == {"name": "rosquilla", "grams": 60, "kcal": 160}

    row = (
        await superuser_conn.execute(
            text("SELECT kind, source, license, created_by FROM foods WHERE id = :id"),
            {"id": str(food_id)},
        )
    ).one()
    # Nunca se disfraza de dato oficial: la fuente y la licencia lo dicen.
    assert (row.kind, row.source) == ("user", "ai_estimate")
    assert "Estimación" in row.license
    assert row.created_by == user_id


async def test_saving_the_same_dish_twice_keeps_a_single_one(two_users, superuser_conn):
    user_id, _ = two_users
    async with AdminSessionLocal() as session:
        first = await estimated_dishes.save_dish(session, user_id, ITEM)
        again = await estimated_dishes.save_dish(
            session, user_id, {**ITEM, "name": "marineras", "kcal": 900}
        )
        await session.commit()

    assert first == again
    count = (
        await superuser_conn.execute(
            text("SELECT count(*) FROM foods WHERE source = 'ai_estimate'")
        )
    ).scalar_one()
    assert count == 1
