"""Expresión de filtro de Meilisearch que se construye a partir de los filtros de la web."""

from myfood.search import FoodFilters, build_filter


def test_filter_expression_ors_within_a_group_and_ands_across_groups():
    filters = FoodFilters(
        supermarkets=("lidl", "aldi"), food_types=("dairy",), nutrition=("high_protein", "low_fat")
    )
    assert build_filter(filters, browsing=False) == [
        ['supermarket = "lidl"', 'supermarket = "aldi"'],
        ['food_group = "dairy"'],
        'nutrition_tags = "high_protein"',
        'nutrition_tags = "low_fat"',
    ]


def test_browsing_hides_sources_without_spanish_names_and_typing_does_not():
    browsing = build_filter(FoodFilters(nutrition=("low_fat",)), browsing=True)
    assert 'source != "usda_sr"' in browsing and 'source != "ciqual"' in browsing
    assert not any("source" in str(c) for c in build_filter(FoodFilters(), browsing=False))


def test_skipping_an_attribute_leaves_its_own_choice_out_of_its_count():
    filters = FoodFilters(supermarkets=("lidl",), food_types=("dairy",))
    counting = build_filter(filters, browsing=False, skip="supermarket")
    assert counting == [['food_group = "dairy"']]
