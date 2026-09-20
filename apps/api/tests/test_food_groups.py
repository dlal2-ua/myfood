"""Grupo alimentario, cantidades razonables y plantillas de comida (`domain/food_groups.py`).

Los nombres son reales (BEDCA y Open Food Facts): el clasificador se ajustó mirando qué grupo
salía de verdad para miles de ellos, y estos casos fijan los errores que se encontraron así."""

import pytest

from myfood.domain import food_groups as fg


@pytest.mark.parametrize(
    ("name", "category", "group"),
    [
        ("Pollo, pechuga, a la plancha", "Cárnicos y derivados", fg.MEAT),
        ("Filete de pechuga de pollo", None, fg.MEAT),
        ("Ternera, solomillo, asado", "Cárnicos y derivados", fg.MEAT),
        ("Cerdo, lomo, asado", "Cárnicos y derivados", fg.MEAT),
        ("Jamón cocido extra", "white hams", fg.PROCESSED_MEAT),
        ("Chorizo sarta extra picante", "chorizo", fg.PROCESSED_MEAT),
        ("Pernil serrano", "serrano ham", fg.PROCESSED_MEAT),
        ("Merluza, cruda", "Pescados, moluscos, reptiles, crustáceos y derivados", fg.FISH),
        ("Bogavante, hervido", "Pescados, moluscos, reptiles, crustáceos y derivados", fg.FISH),
        ("Atún claro en aceite de oliva", "canned tunas", fg.FISH),
        ("Sardinillas en aceite de oliva", "sardines in oil", fg.FISH),
        ("Tonyina clara", "tunas in oil", fg.FISH),
        ("Aceite de hígado de bacalao", "Grasas y aceites", fg.OTHER),
        ("Huevo de gallina, cocido", "Huevos y derivados", fg.EGG),
        ("Huevos frescos L", "fresh eggs", fg.EGG),
        ("Ous de Pagès", "eggs", fg.EGG),
        ("Leche semidesnatada", "milks", fg.DAIRY),
        ("Yogur natural", "plain yogurts", fg.DAIRY),
        ("Bebida de avena con calcio", "oat based drinks", fg.DAIRY),
        ("Bifidus cremoso con ciruela y kiwi", "Lácteos y derivados", fg.DAIRY),
        ("Queso fresco", "Lácteos y derivados", fg.CHEESE),
        ("Formatge de cabra", "goat cheeses", fg.CHEESE),
        ("Lenteja, en conserva", "Legumbres, semillas, frutos secos y derivados", fg.LEGUME),
        ("Garbanzos cocidos al natural", "canned chickpeas", fg.LEGUME),
        ("Tofu", "plain tofu", fg.LEGUME),
        ("Judías verdes finas cortadas", "canned green beans", fg.VEGETABLE),
        ("Guisante, congelado, crudo", "Verduras, hortalizas y derivados", fg.VEGETABLE),
        ("Brócoli", "Verduras, hortalizas y derivados", fg.VEGETABLE),
        ("Champiñones laminados bajos en sal", "verduras en conserva y tarro", fg.VEGETABLE),
        ("Arenque, salado", "Pescados, moluscos, reptiles, crustáceos y derivados", fg.FISH),
        ("Manzana, con piel, cruda", "Frutas y derivados", fg.FRUIT),
        ("Uva negra, cruda", "Frutas y derivados", fg.FRUIT),
        ("Arroz, hervido", "Cereales y derivados", fg.GRAIN),
        ("Spaghetti al huevo", None, fg.GRAIN),
        ("Pasta alimenticia, integral, hervida", "Cereales y derivados", fg.GRAIN),
        ("Patata, hervida", "Verduras, hortalizas y derivados", fg.GRAIN),
        ("Copos de avena", "Cereales y derivados", fg.CEREAL),
        ("Cereales desayuno base de maíz y miel", "Cereales y derivados", fg.CEREAL),
        ("Pan de molde con Centeno y Semillas", "sliced breads", fg.BREAD),
        ("Pa de motlle", "sliced breads", fg.BREAD),
        ("Barra de pan", "breads", fg.BREAD),
        ("Almendra natural", "raw almonds", fg.NUTS),
        ("Castaña, tostada", "Legumbres, semillas, frutos secos y derivados", fg.NUTS),
        ("Aceite de oliva virgen extra", "extra virgin olive oils", fg.OIL_FAT),
        ("Mantequilla", "butters", fg.OIL_FAT),
        # Lo que el motor no usa para armar comidas.
        ("Galletas María", "biscuits", fg.SWEET),
        ("Chocolate negro, con azúcar", "Azúcar, chocolate y derivados", fg.SWEET),
        ("Mermelada de melocotón", "peach jams", fg.SWEET),
        ("Helados Classic", None, fg.SWEET),
        ("Triángulos de maíz sabor queso", "corn chips", fg.SNACK),
        ("Patatas fritas onduladas sabor jamón", "potato crisps", fg.SNACK),
        ("Zumo de naranja", "orange juices", fg.BEVERAGE),
        ("Naranja", "orange nectars", fg.BEVERAGE),
        ("Agua mineral natural", None, fg.BEVERAGE),
        ("Pizza atún y bacon", None, fg.PREPARED),
        ("Lasaña boloñesa vegetal", "vegetarian lasagne", fg.PREPARED),
        ("Tortilla de patata con cebolla", "spanish omelettes", fg.PREPARED),
        ("Pechuga empanada marinada", "Pechuga de pollo empanada", fg.PREPARED),
        ("Salsa yogur", "Groceries", fg.PREPARED),
        ("Burguer vegetal brócoli", None, fg.PREPARED),
        ("Sesos, de cordero, crudos", "Cárnicos y derivados", fg.OTHER),
        ("Corazón de pollo, crudo", "Cárnicos y derivados", fg.OTHER),
        ("Aceitunas rellenas de anchoa", "green stuffed olives", fg.OTHER),
        ("Nata", "ice creams", fg.OTHER),
        ("Focaccia de calabaza DESCATALOGADO", None, fg.PREPARED),
    ],
)
def test_classify_food(name, category, group):
    assert fg.classify_food(name, category) == group


def test_a_name_that_says_nothing_falls_back_to_the_category():
    assert fg.classify_food("Rosca", "Cereales y derivados") == fg.GRAIN


def test_unknown_food_has_no_group():
    assert fg.classify_food("Xyzzy", None) == fg.OTHER
    assert fg.classify_food(None, None) == fg.OTHER


def test_only_plannable_groups_are_used_to_build_meals():
    for excluded in (fg.SWEET, fg.BEVERAGE, fg.SNACK, fg.PREPARED, fg.OTHER):
        assert excluded not in fg.PLANNABLE_GROUPS
    assert fg.MEAT in fg.PLANNABLE_GROUPS


@pytest.mark.parametrize(
    ("group", "name", "staple"),
    [
        (fg.MEAT, "Pollo, pechuga, a la plancha", True),
        (fg.FISH, "Merluza, cruda", True),
        (fg.FISH, "Bogavante, hervido", False),
        (fg.VEGETABLE, "Tomate, maduro, crudo", True),
        (fg.VEGETABLE, "Trufa, cruda", False),
        (fg.FRUIT, "Fresa", True),
        (fg.FRUIT, "L Casei sabor fresa", False),
        (fg.DAIRY, "Leche semidesnatada", True),
        (fg.DAIRY, "Tsatsiki a base de yogur griego", False),
        (fg.EGG, "Huevo de gallina, cocido", True),
        (fg.EGG, "Huevo de pato, crudo", False),
        (None, "Pollo", False),
    ],
)
def test_staples_are_everyday_foods(group, name, staple):
    assert fg.is_staple(group, name) is staple


def test_dry_foods_have_smaller_portions_than_cooked_ones():
    cooked = fg.gram_bounds(fg.GRAIN, 130)
    dry = fg.gram_bounds(fg.GRAIN, 350)
    assert dry.max_g < cooked.max_g
    assert fg.gram_bounds(fg.LEGUME, 340).max_g < fg.gram_bounds(fg.LEGUME, 116).max_g
    assert fg.gram_bounds(fg.FRUIT, 300).max_g < fg.gram_bounds(fg.FRUIT, 52).max_g


def test_an_unknown_group_gets_the_default_bounds():
    assert fg.gram_bounds(None, 100) == fg.GramBounds(20, 400)
    assert fg.gram_bounds("nope", 100) == fg.GramBounds(20, 400)


def test_kcal_shares_of_every_meal_count_sum_to_one():
    for meals, shares in fg.MEAL_KCAL_SHARES.items():
        assert len(shares) == meals
        assert sum(shares.values()) == pytest.approx(1.0)


def test_main_meals_need_a_protein_and_a_vegetable_and_breakfast_a_carb_and_a_dairy_or_egg():
    lunch = fg.MEAL_TEMPLATES["lunch"]
    assert any(fg.MEAT in group for group in lunch.required)
    assert any(group == frozenset({fg.VEGETABLE}) for group in lunch.required)
    breakfast = fg.MEAL_TEMPLATES["breakfast"]
    assert any(fg.BREAD in group for group in breakfast.required)
    assert any(fg.DAIRY in group for group in breakfast.required)


def test_rice_and_pasta_do_not_belong_at_breakfast_and_cereal_does_not_belong_at_lunch():
    assert fg.GRAIN not in fg.MEAL_TEMPLATES["breakfast"].caps
    assert fg.CEREAL in fg.MEAL_TEMPLATES["breakfast"].caps
    assert fg.CEREAL not in fg.MEAL_TEMPLATES["lunch"].caps
    assert fg.CEREAL not in fg.MEAL_TEMPLATES["dinner"].caps
