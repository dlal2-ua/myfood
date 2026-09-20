"""Seed de factores de cocción (`etl/seeds/cooking_yields.csv`)."""

import pytest

from etl.sources import cooking_yields as cy

RULES = cy.load_rules()


def _factor(name, source="bedca"):
    return cy.assign_factors([("id", source, name)], RULES).get("id")


def test_the_seed_only_has_positive_factors_for_known_sources():
    assert RULES
    assert {r.source for r in RULES} <= {"bedca", "usda_foundation", "usda_sr", "ciqual"}
    assert all(r.factor > 0 for r in RULES)


@pytest.mark.parametrize(
    ("name", "factor"),
    [
        ("Arroz integral, crudo", 2.6),
        ("Arroz, blanco, crudo", 2.8),
        ("Pasta alimenticia, cruda", 2.2),
        ("Pasta alimenticia, integral, cruda", 2.2),
        ("Lenteja, seca, cruda", 2.4),
        ("Garbanzo, seco, crudo", 2.3),
        ("Alubia blanca, seca, cruda", 2.4),
        ("Haba, seca", 2.2),
        ("Pollo, pechuga, con piel, crudo", 0.75),
        ("Ternera, solomillo, sin grasa, crudo", 0.70),
        ("Merluza, congelada, cruda", 0.80),
    ],
)
def test_raw_staples_get_their_factor(name, factor):
    assert _factor(name) == factor


@pytest.mark.parametrize(
    "name",
    [
        "Arroz, hervido",  # ya cocinado: no tiene sentido un factor sobre el crudo
        "Lenteja, en conserva",
        "Haba, seca, remojada, hervida",
        "Corazón de pollo, crudo",
        "Pollo asado",
    ],
)
def test_cooked_or_unrelated_foods_get_none(name):
    assert _factor(name) is None


def test_the_specific_rule_wins_over_the_general_one():
    # «Arroz integral, crudo» encaja con las dos reglas de arroz: gana la primera (más específica)
    assert _factor("Arroz integral, crudo") == 2.6


def test_a_rule_only_applies_to_its_own_source():
    assert _factor("Arroz, blanco, crudo", source="off") is None
