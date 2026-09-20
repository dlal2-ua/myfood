from myfood.domain.quantity_text import DEFAULT_SERVING_GRAMS, resolve_grams


def test_explicit_grams_wins_over_serving_size():
    assert resolve_grams("200 g", serving_size_g=50) == 200.0
    assert resolve_grams("150gr", serving_size_g=None) == 150.0
    assert resolve_grams("250 gramos", serving_size_g=50) == 250.0


def test_digit_quantity_multiplies_serving_size():
    assert resolve_grams("2", serving_size_g=60) == 120.0
    assert resolve_grams("3 unidades", serving_size_g=60) == 180.0


def test_spanish_number_words_multiply_serving_size():
    assert resolve_grams("dos huevos", serving_size_g=60) == 120.0
    assert resolve_grams("una tostada", serving_size_g=40) == 40.0
    assert resolve_grams("tres piezas", serving_size_g=30) == 90.0


def test_unrecognized_text_defaults_to_one_unit():
    assert resolve_grams("una ración generosa", serving_size_g=80) == 80.0
    assert resolve_grams("ración habitual", serving_size_g=80) == 80.0


def test_missing_serving_size_falls_back_to_default():
    assert resolve_grams("una ración", serving_size_g=None) == DEFAULT_SERVING_GRAMS
    assert resolve_grams("dos raciones", serving_size_g=None) == DEFAULT_SERVING_GRAMS * 2


def test_word_boundary_does_not_match_substrings():
    # "una" no debe disparar el valor de "un" como substring.
    assert resolve_grams("una manzana", serving_size_g=100) == 100.0


# --- pesos de una unidad por grupo, medidas caseras y unidades explícitas (Fase 8) --------------

import pytest  # noqa: E402


@pytest.mark.parametrize(
    ("text", "name", "category", "expected"),
    [
        ("6 huevos", "Huevo de gallina, cocido", None, 360.0),  # antes 600 g
        ("dos huevos fritos", "Huevo de gallina, frito", None, 120.0),
        ("una manzana", "Manzana, con piel, cruda", "Frutas y derivados", 130.0),
        ("dos tostadas", "Pan tostado", "toasts", 60.0),  # antes 200 g
        ("un yogur", "Yogur natural", "plain yogurts", 125.0),
        ("una loncha", "Jamón cocido extra", "white hams", 20.0),
        ("un filete", "Ternera, solomillo, a la plancha", "Cárnicos y derivados", 150.0),
        ("un plato", "Lentejas, cocidas", None, 250.0),
    ],
)
def test_a_unit_weighs_what_its_food_group_typically_weighs(text, name, category, expected):
    assert resolve_grams(text, None, food_name=name, category=category) == expected


def test_the_label_serving_still_beats_the_group_default():
    assert resolve_grams("dos", 45, food_name="Huevo de gallina, cocido") == 90.0


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("una cucharada", 15.0),
        ("2 cucharadas", 30.0),
        ("una cucharadita", 5.0),
        ("un vaso", 200.0),
        ("dos vasos", 400.0),
        ("una taza", 250.0),
        ("un puñado", 30.0),
        ("media taza", 125.0),
    ],
)
def test_home_measures(text, expected):
    assert resolve_grams(text, serving_size_g=None, food_name="Leche desnatada") == expected


def test_a_spoonful_of_oil_weighs_less_than_one_of_powder():
    assert resolve_grams("una cucharada", None, food_name="Aceite de oliva virgen extra") == 10.0
    assert resolve_grams("una cucharada", None, food_name="Cacao en polvo") == 15.0


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1 kg", 1000.0),
        ("1,5 kg", 1500.0),
        ("250 ml", 250.0),
        ("medio litro", 500.0),
        ("un kilo", 1000.0),
        ("medio kilo", 500.0),
        ("2 l", 2000.0),
    ],
)
def test_explicit_weights_and_volumes(text, expected):
    assert resolve_grams(text, serving_size_g=30) == expected


def test_half_a_unit():
    assert resolve_grams("media manzana", None, food_name="Manzana", category=None) == 65.0


def test_an_unknown_food_still_falls_back_to_the_default_portion():
    assert resolve_grams("dos", None, food_name="Xyzzy") == DEFAULT_SERVING_GRAMS * 2
