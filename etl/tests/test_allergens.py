# ruff: noqa: E501  (tablas de casos de prueba: una línea por caso es más legible)
"""Clasificador de alérgenos de alimentos genéricos (`etl/transform/allergens.py`).

Es una heurística que prefiere errar por exceso, así que los tests fijan (a) los
casos claros de cada alérgeno en los tres idiomas de las fuentes (USDA inglés,
BEDCA español, CIQUAL francés) y (b) alimentos comunes que NO deben marcarse,
porque un exceso de falsos positivos dejaría sin opciones a quien tiene la
restricción."""

import pytest

from etl.transform.allergens import ALL_CODES, classify_generic, off_tags_to_codes


@pytest.mark.parametrize(
    ("name_es", "name_en", "category", "expected"),
    [
        # --- USDA (inglés) ---
        ("Milk, whole, 3.25% milkfat", None, "Dairy and Egg Products", {"lacteos"}),
        ("Cheese, cheddar", None, "Dairy and Egg Products", {"lacteos"}),
        ("Butter, salted", None, "Dairy and Egg Products", {"lacteos"}),
        ("Egg, whole, raw, fresh", None, "Dairy and Egg Products", {"huevos"}),
        ("Fast foods, cheeseburger; single, large patty", None, "Fast Foods", {"lacteos", "gluten"}),
        ("Cheesecake, prepared from recipe", None, "Baked Products", {"lacteos", "gluten"}),
        ("Wheat flour, white, all-purpose", None, "Cereal Grains and Pasta", {"gluten"}),
        ("Bread, white, commercially prepared", None, "Baked Products", {"gluten"}),
        ("Spaghetti, cooked", None, "Cereal Grains and Pasta", {"gluten"}),
        ("Fish, salmon, Atlantic, farmed, raw", None, "Finfish and Shellfish Products", {"pescado"}),
        ("Crustaceans, shrimp, mixed species, raw", None, "Finfish and Shellfish Products", {"crustaceos", "pescado"}),
        ("Mollusks, mussel, blue, raw", None, "Finfish and Shellfish Products", {"moluscos", "pescado"}),
        ("Peanuts, all types, raw", None, "Legumes and Legume Products", {"cacahuetes"}),
        ("Peanut butter, smooth style", None, "Legumes and Legume Products", {"cacahuetes"}),
        ("Nuts, almonds", None, "Nut and Seed Products", {"frutos_de_cascara"}),
        ("Nuts, walnuts, english", None, "Nut and Seed Products", {"frutos_de_cascara"}),
        ("Tofu, raw, firm", None, "Legumes and Legume Products", {"soja"}),
        ("Soy sauce made from soy and wheat (shoyu)", None, "Legumes and Legume Products", {"soja", "gluten"}),
        ("Celery, raw", None, "Vegetables and Vegetable Products", {"apio"}),
        ("Mustard, prepared, yellow", None, "Spices and Herbs", {"mostaza"}),
        ("Seeds, sesame seeds, whole, dried", None, "Nut and Seed Products", {"sesamo"}),
        ("Alcoholic beverage, wine, table, red", None, "Alcoholic Beverages", {"sulfitos"}),
        ("Lupins, mature seeds, raw", None, "Legumes and Legume Products", {"altramuces"}),
        # --- BEDCA (español + inglés) ---
        ("Mantequilla salada", "Butter with salt", "Grasas y aceites", {"lacteos"}),
        ("Galletas, de mantequilla", "Butter cookie", "Cereales y derivados", {"gluten", "lacteos"}),
        ("Germen de trigo", "Wheat germ", "Cereales y derivados", {"gluten"}),
        ("Mejillones, crudos", "Mussels, raw", "Pescados y mariscos", {"moluscos", "pescado"}),
        # --- CIQUAL (francés) ---
        ("Farine de seigle T85", None, None, {"gluten"}),
        ("Jambon de Bayonne", None, "charcuteries et assimilés", set()),
        ("Sardine, sauce tomate, appertisée, égouttée", None, "produits à base de poissons", {"pescado"}),
        ("Lait demi-écrémé", None, None, {"lacteos"}),
        ("Crevette, cuite", None, None, {"crustaceos"}),
    ],
)
def test_common_foods_get_their_allergens(name_es, name_en, category, expected):
    result = classify_generic(name_es, name_en, category)
    assert expected <= result, f"{name_es!r}: esperaba al menos {expected}, salió {result}"


@pytest.mark.parametrize(
    "name",
    [
        "Beans, snap, green, canned, regular pack, drained solids",
        "Rice, white, long-grain, regular, raw, enriched",
        "Chicken, broilers or fryers, breast, meat only, cooked, roasted",
        "Lamb, Australian, imported, fresh, leg, cooked, pan-fried",
        "Apples, raw, with skin",
        "Bananas, raw",
        "Potatoes, baked, flesh and skin",
        "Oil, olive, salad or cooking",
        "Beef, ground, 85% lean meat / 15% fat, raw",
        "Eggplant, raw",
        "Nutmeg, ground",
        "Nuts, coconut meat, raw",
        "Nuts, chestnuts, european, raw",
        "Coconut milk, raw",
        "Cocoa butter",
        "Tomatoes, red, ripe, raw",
        "Broccoli, cooked, boiled, drained",
        "Manzana",
        "Arroz blanco cocido",
        "Aceite de oliva virgen extra",
        "Pomme de terre, cuite",
    ],
)
def test_common_allergen_free_foods_are_not_flagged(name):
    assert classify_generic(name) == set(), f"{name!r} no debería marcar alérgenos"


def test_plant_milks_are_not_dairy_but_keep_their_own_allergen():
    assert "lacteos" not in classify_generic("Leche de almendras sin azúcar")
    assert "frutos_de_cascara" in classify_generic("Leche de almendras sin azúcar")
    assert "lacteos" not in classify_generic("Soy milk, original and vanilla, unfortified")
    assert "soja" in classify_generic("Soy milk, original and vanilla, unfortified")


def test_accents_and_case_do_not_matter():
    assert "moluscos" in classify_generic("MEJILLÓN en escabeche")
    assert "moluscos" in classify_generic("mejillon en escabeche")


def test_category_hint_adds_dairy_but_not_when_the_name_says_it_is_an_egg():
    assert "lacteos" in classify_generic("Whipped topping", None, "Dairy and Egg Products")
    result = classify_generic("Egg substitute, powder", None, "Dairy and Egg Products")
    assert "huevos" in result and "lacteos" not in result


def test_returns_only_known_codes():
    assert classify_generic("Milk, egg, wheat, fish, peanut, soy, sesame, mustard") <= ALL_CODES


def test_off_tags_map_to_our_codes_and_ignore_unknown_ones():
    assert off_tags_to_codes(["en:gluten", "en:milk", "en:none", "fr:foo"]) == {"gluten", "lacteos"}
    assert off_tags_to_codes(["en:sulphur-dioxide-and-sulphites"]) == {"sulfitos"}
    assert off_tags_to_codes(None) == set()
    assert off_tags_to_codes([]) == set()
