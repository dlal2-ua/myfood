"""Afinar con el catálogo lo que estima el modelo (`domain/catalog_refine.py`).

Lo que se prueba es, sobre todo, lo que NO debe confirmarse: el catálogo solo sustituye a una
estimación cuando es el mismo alimento. Los casos salen de evaluar contra el catálogo real,
donde el buscador devolvía una quesadilla salvadoreña para «pan» y una mayonesa light para
«aceite de oliva».
"""

import pytest

from myfood.domain.catalog_refine import CatalogFood, CatalogIndex, significant_tokens


def food(name: str, kcal: float, source: str = "ciqual") -> CatalogFood:
    tokens = significant_tokens(name)
    return CatalogFood(
        food_id=name,
        name=name,
        source=source,
        tokens=frozenset(tokens),
        first_token=tokens[0],
        kcal_100g=kcal,
        protein_100g=0,
        fat_100g=0,
        carbs_100g=0,
    )


INDEX = CatalogIndex(
    [
        food("Pan blanco de barra sin sal", 262, "bedca"),
        food("Pan, sin gluten", 261),
        food("Pan de avena", 270, "bedca"),
        food("Pan, dulce de queso salvadoreño", 374, "usda_sr"),
        food("Aceite de oliva", 884, "usda_sr"),
        food("Sardina en aceite de oliva, escurrida", 202),
        food("Mayonesa light con aceite de oliva", 361, "usda_sr"),
        food("Jamón curado Serrano", 235),
        food("Jamón de cerdo entero, crudo", 245, "usda_sr"),
        food("Jamón curado de Parma", 248),
        food("Lentejas, crudas", 352, "usda_sr"),
        food("Lentejas cocidas", 116, "usda_sr"),
        food("Lentejas germinadas salteadas", 101, "usda_sr"),
        food("Rosquillas de bizcocho naturales", 434, "usda_sr"),
        food("Pechuga de pavo sin piel a la plancha", 145, "bedca"),
        food("Pechuga de pollo con piel, cruda", 157),
        food("Pechuga de pollo sin piel, asada", 165, "usda_sr"),
        food("Tomate, crudo", 19),
        food("Tomate, seco al sol", 258, "usda_sr"),
        food("Sepia cruda", 79, "usda_sr"),
        food("Sepia cocida", 158, "usda_sr"),
        food("Cerveza", 43, "usda_sr"),
    ]
)


def match(name: str, kcal_100g: float | None) -> str | None:
    found = INDEX.best_match(name, kcal_100g)
    return found.name if found else None


@pytest.mark.parametrize(
    ("name", "kcal_100g", "expected"),
    [
        # El de toda la vida antes que una variante, aunque la variante se llame más corto.
        ("pan", 260, "Pan blanco de barra sin sal"),
        ("aceite de oliva", 900, "Aceite de oliva"),
        ("jamón serrano", 250, "Jamón curado Serrano"),
        # «Jamón» a secas es antes un curado que una pierna de cerdo cruda.
        ("jamón", 250, "Jamón curado de Parma"),
        # Guisadas no está, pero cocidas es el mismo alimento en el mismo estado.
        ("lentejas guisadas", 110, "Lentejas cocidas"),
        ("pechuga de pollo a la plancha", 163, "Pechuga de pollo sin piel, asada"),
        ("tomate", 20, "Tomate, crudo"),
        ("huevos fritos (2)", 180, None),
        ("cerveza", 45, "Cerveza"),
    ],
)
def test_the_catalog_confirms_the_same_food(name, kcal_100g, expected):
    assert match(name, kcal_100g) == expected


@pytest.mark.parametrize(
    ("name", "kcal_100g", "why"),
    [
        ("pan de cristal", 256, "el catálogo no tiene pan de cristal: no vale otro pan"),
        ("rosquilla de pan", 267, "una rosquilla dulce no es una rosquilla de pan"),
        ("lentejas guisadas", 350, "las únicas con esas calorías son las crudas"),
        ("sepia a la plancha", 106, "ni la cruda (79) ni la cocida (158) coinciden"),
        ("caña de cerveza", 45, "«caña» no está en el catálogo"),
        ("ensaladilla rusa", 150, "no hay nada que se llame así"),
        ("oliva", 884, "el aceite no EMPIEZA por «oliva»... y sí: es el aceite, no la oliva"),
        ("", 100, "sin nombre no hay nada que buscar"),
        ("a la plancha", 100, "solo dice cómo está cocinado, no qué es"),
    ],
)
def test_a_different_food_never_replaces_the_estimate(name, kcal_100g, why):
    assert match(name, kcal_100g) is None, why


def test_the_calories_have_to_agree():
    """Es la condición que impide confirmar con el alimento equivocado: si el catálogo dice
    algo muy distinto de lo que esperaba el modelo, lo normal es que no sea lo mismo."""
    assert match("lentejas", 110) == "Lentejas cocidas"
    assert match("lentejas", 340) == "Lentejas, crudas"
    assert match("lentejas", 200) is None
    # Con muy pocas calorías un 20 % no es nada: hay un margen absoluto.
    assert match("tomate", 25) == "Tomate, crudo"
    assert match("tomate", 60) is None


def test_without_an_estimate_only_an_exact_name_counts():
    assert match("cerveza", None) == "Cerveza"
    assert match("aceite de oliva", None) == "Aceite de oliva"
    assert match("pan", None) is None
    assert match("jamón", None) is None


def test_stopwords_numbers_and_plurals_do_not_matter():
    assert significant_tokens("Huevos fritos (2) con las patatas") == [
        "huevo", "frito", "patata",
    ]
    assert significant_tokens("Pan, de trigo") == ["pan", "trigo"]
