"""Taxonomía de filtros del catálogo (`domain/food_taxonomy.py`): supermercado a partir de la
marca de OFF, tipo de alimento y etiquetas de nutrición por 100 g."""

import pytest

from myfood.domain.food_taxonomy import (
    FOOD_TYPE_LABELS,
    NUTRITION_TAGS,
    SUPERMARKET_LABELS,
    food_type_for,
    nutrition_tags,
    supermarket_for_brand,
)


@pytest.mark.parametrize(
    ("brand", "expected"),
    [
        ("Hacendado, MERCADONA", "mercadona"),
        ("mercadona", "mercadona"),
        ("Delisano, mercadona", "mercadona"),
        ("Milbona, Lidl", "lidl"),
        ("Bio Organic, Lidl, Sondey", "lidl"),
        ("Auchan, Gullón", "alcampo"),
        ("Carrefour BIO, Carrefour", "carrefour"),
        ("CRF Específicos - Sin Gluten, Carrefour", "carrefour"),
        ("DÍA", "dia"),
        ("Dia, Dia - Distribuidora Internacional de Alimentación S.A.", "dia"),
        ("El Corte Inglés, Special Line", "el_corte_ingles"),
        ("El Corte Ingles", "el_corte_ingles"),
        ("CONSUM S. COOP. V., consum", "consum"),
        ("Aldi, Golden Bridge", "aldi"),
        ("Ahorramás", "ahorramas"),
    ],
)
def test_store_brands_map_to_their_chain(brand, expected):
    assert supermarket_for_brand(brand) == expected
    assert expected in SUPERMARKET_LABELS


@pytest.mark.parametrize("brand", [None, "", "  ", "Herbalife", "Diapers Co", "Dial", "Kellogg's"])
def test_manufacturer_brands_are_not_a_supermarket(brand):
    assert supermarket_for_brand(brand) is None


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Pechuga de pollo a la plancha", "meat"),
        ("Yogur natural", "dairy"),
        ("Aceite de oliva virgen extra", "oil_fat"),
        ("Manzana", "fruit"),
    ],
)
def test_food_type_uses_the_shared_group_rules(name, expected):
    assert food_type_for(name, None) == expected
    assert expected in FOOD_TYPE_LABELS


def test_unrecognised_food_has_no_type_instead_of_a_made_up_one():
    assert food_type_for("Xyzzy plugh", None) is None
    assert food_type_for("Fórmula infantil", None) is None  # el grupo «other» no se filtra


def test_chicken_breast_tags():
    tags = nutrition_tags(kcal=165, protein=31, fat=3.6, carbs=0)
    assert "high_protein" in tags and "low_carb" in tags
    assert "low_fat" not in tags  # 3,6 g > 3 g
    assert "low_calorie" not in tags


def test_leafy_vegetable_is_light_but_not_high_protein():
    tags = nutrition_tags(kcal=23, protein=2.9, fat=0.4, carbs=3.6)
    assert {"low_calorie", "low_fat", "low_carb"} <= set(tags)
    assert "high_protein" not in tags  # 2,9 g no llega a los 8 g mínimos


def test_a_missing_value_never_earns_a_tag():
    tags = nutrition_tags(kcal=100, protein=10, fat=5, carbs=10)
    assert not {"low_sugar", "sugar_free", "low_saturated", "high_fiber", "low_salt"} & set(tags)
    assert not {"nutriscore_ab", "minimally_processed"} & set(tags)


@pytest.mark.parametrize(
    ("sugars", "low", "free"),
    [(0.5, True, True), (0.6, True, False), (5, True, False), (5.1, False, False)],
)
def test_sugar_thresholds(sugars, low, free):
    tags = nutrition_tags(kcal=100, protein=1, fat=1, carbs=20, sugars=sugars)
    assert ("low_sugar" in tags) is low
    assert ("sugar_free" in tags) is free


def test_fibre_salt_and_saturated_thresholds():
    tags = nutrition_tags(kcal=300, protein=10, fat=10, carbs=40, saturated=1.5, fiber=6, salt=0.3)
    assert {"low_saturated", "high_fiber", "low_salt"} <= set(tags)
    tags = nutrition_tags(
        kcal=300, protein=10, fat=10, carbs=40, saturated=1.6, fiber=5.9, salt=0.31
    )
    assert not {"low_saturated", "high_fiber", "low_salt"} & set(tags)


def test_score_tags():
    assert "nutriscore_ab" in nutrition_tags(kcal=1, protein=0, fat=0, carbs=0, nutriscore="B")
    assert "nutriscore_ab" not in nutrition_tags(kcal=1, protein=0, fat=0, carbs=0, nutriscore="c")
    assert "minimally_processed" in nutrition_tags(kcal=1, protein=0, fat=0, carbs=0, nova=2)
    assert "minimally_processed" not in nutrition_tags(kcal=1, protein=0, fat=0, carbs=0, nova=4)


def test_the_declared_tags_are_exactly_the_ones_the_function_can_emit():
    emitted = set(
        nutrition_tags(
            kcal=10, protein=9, fat=0, carbs=0, saturated=0, sugars=0, fiber=10, salt=0,
            nutriscore="a", nova=1,
        )
    )
    assert emitted == {t.code for t in NUTRITION_TAGS}
