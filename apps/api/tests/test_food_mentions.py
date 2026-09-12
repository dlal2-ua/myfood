from myfood.domain.food_mentions import split_into_food_mentions


def test_splits_on_y_con_and_commas():
    assert split_into_food_mentions("dos huevos fritos y una tostada con aceite") == [
        "huevos fritos",
        "tostada",
        "aceite",
    ]


def test_splits_on_comma_and_semicolon():
    assert split_into_food_mentions("arroz, pollo; brócoli") == ["arroz", "pollo", "brócoli"]


def test_strips_leading_digit_quantity():
    assert split_into_food_mentions("3 tostadas") == ["tostadas"]


def test_single_food_with_no_connectors_returns_itself():
    assert split_into_food_mentions("manzana") == ["manzana"]


def test_blank_text_returns_empty_list():
    assert split_into_food_mentions("   ") == []


def test_fragment_that_is_only_a_quantity_word_falls_back_to_itself():
    # "una" solo, sin nada detrás que quitar, no debe quedar vacío.
    assert split_into_food_mentions("una") == ["una"]
