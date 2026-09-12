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
    assert resolve_grams("un puñado", serving_size_g=50) == 50.0
    assert resolve_grams("una ración generosa", serving_size_g=80) == 80.0
    assert resolve_grams("ración habitual", serving_size_g=80) == 80.0


def test_missing_serving_size_falls_back_to_default():
    assert resolve_grams("una ración", serving_size_g=None) == DEFAULT_SERVING_GRAMS
    assert resolve_grams("dos raciones", serving_size_g=None) == DEFAULT_SERVING_GRAMS * 2


def test_word_boundary_does_not_match_substrings():
    # "una" no debe disparar el valor de "un" como substring.
    assert resolve_grams("una manzana", serving_size_g=100) == 100.0
