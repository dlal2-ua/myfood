"""Tests de transformación OFF con muestras reales (documento 2, sección 16)."""

import json
from pathlib import Path

import pytest

from etl.db import ParsedFood
from etl.rejected import Rejection
from etl.sources.off import _grade, _nova, _per_100g, parse_food

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _load_fixture() -> list[dict]:
    with (FIXTURES / "off_sample.json").open(encoding="utf-8") as f:
        return json.load(f)["products"]


def test_parse_real_product_maps_macros():
    nata = _load_fixture()[0]
    assert nata["code"] == "8410297121104"

    result = parse_food(nata)

    assert isinstance(result, ParsedFood)
    assert result.source == "off"
    assert result.kind == "branded"
    assert result.source_id == "8410297121104"
    assert result.barcode_ean == "8410297121104"
    assert result.name_es == "Nata Montada Azucarada"
    assert result.kcal_100g == 306
    assert result.protein_100g == 2.4
    assert result.fat_100g == 28
    assert result.carbs_100g == 11
    assert result.salt_100g == 0.08
    assert result.quality_rank == 5
    assert result.license == "ODbL"


def test_parse_real_product_copies_off_scores_directly():
    """Nutri-Score/NOVA/Eco-Score se copian tal cual, nunca se calculan (sección 21)."""
    nata = _load_fixture()[0]
    result = parse_food(nata)
    assert isinstance(result, ParsedFood)
    assert result.nutriscore_grade == "d"
    assert result.nova_group == 4
    assert result.ecoscore_grade == "b"


def test_parse_second_real_product():
    cereal = _load_fixture()[1]
    result = parse_food(cereal)
    assert isinstance(result, ParsedFood)
    assert result.kcal_100g == pytest.approx(373.333, abs=1e-2)
    assert result.fiber_100g == 4.4
    assert result.nova_group == 3


def test_missing_barcode_is_rejected():
    result = parse_food({"code": "", "product_name": "Sin código"})
    assert isinstance(result, Rejection)
    assert result.reason == "MISSING_BARCODE"


def test_missing_name_is_rejected():
    result = parse_food({"code": "123", "product_name": "", "product_name_es": ""})
    assert isinstance(result, Rejection)
    assert result.reason == "MISSING_NAME"


def test_missing_kcal_is_rejected():
    result = parse_food({"code": "123", "product_name": "Sin nutrientes", "nutriments": {}})
    assert isinstance(result, Rejection)
    assert result.reason == "MISSING_KCAL"


def test_kcal_above_900_is_rejected():
    result = parse_food(
        {
            "code": "123",
            "product_name": "Imposible",
            "nutriments": {"energy-kcal_100g": 950},
        }
    )
    assert isinstance(result, Rejection)
    assert result.reason == "KCAL_OUT_OF_RANGE"


def test_macros_exceeding_100g_is_rejected():
    result = parse_food(
        {
            "code": "123",
            "product_name": "Macros imposibles",
            "nutriments": {
                "energy-kcal_100g": 400,
                "proteins_100g": 60,
                "fat_100g": 30,
                "carbohydrates_100g": 30,
            },
        }
    )
    assert isinstance(result, Rejection)
    assert result.reason == "MACROS_EXCEED_100G"


def test_prefers_spanish_name_over_generic():
    result = parse_food(
        {
            "code": "123",
            "product_name": "Generic Name",
            "product_name_es": "Nombre en español",
            "nutriments": {"energy-kcal_100g": 100},
        }
    )
    assert isinstance(result, ParsedFood)
    assert result.name_es == "Nombre en español"
    assert result.name_en == "Generic Name"


def test_falls_back_to_generic_name_when_no_spanish():
    result = parse_food(
        {
            "code": "123",
            "product_name": "Only Generic",
            "nutriments": {"energy-kcal_100g": 100},
        }
    )
    assert isinstance(result, ParsedFood)
    assert result.name_es == "Only Generic"
    assert result.name_en is None  # mismo texto, no se duplica


def test_per_100g_uses_direct_value_when_present():
    assert _per_100g({"sugars_100g": 5.0}, "sugars", None) == 5.0


def test_per_100g_converts_from_serving_when_100g_missing():
    # 3 g de azúcar en una porción de 15 g -> 20 g/100g
    nutriments = {"sugars_serving": 3.0}
    assert _per_100g(nutriments, "sugars", serving_quantity=15.0) == pytest.approx(20.0)


def test_per_100g_none_without_serving_size_never_estimates():
    """Sin serving_size no se estima nada — se descarta el dato (sección 11.2)."""
    nutriments = {"sugars_serving": 3.0}
    assert _per_100g(nutriments, "sugars", serving_quantity=None) is None


def test_grade_accepts_valid_letters():
    assert _grade("a") == "a"
    assert _grade("E") == "e"  # OFF a veces manda mayúsculas


def test_grade_rejects_non_letter_values():
    # OFF usa 'unknown'/'not-applicable' cuando no hay nota — nunca se
    # inventa una letra ni se deja pasar tal cual a una columna CHAR(1).
    assert _grade("unknown") is None
    assert _grade("not-applicable") is None
    assert _grade(None) is None
    assert _grade("") is None


def test_nova_accepts_valid_range():
    assert _nova(1) == 1
    assert _nova("4") == 4


def test_nova_rejects_out_of_range_or_invalid():
    assert _nova(0) is None
    assert _nova(5) is None
    assert _nova(None) is None
    assert _nova("not-a-number") is None


def test_parse_food_rejects_garbage_grade_before_hitting_db():
    """Regresión: un nutriscore_grade tipo 'unknown' rompía el INSERT
    (columna CHAR(1)) en la carga real contra Postgres."""
    result = parse_food(
        {
            "code": "123",
            "product_name": "Con nota desconocida",
            "nutriscore_grade": "unknown",
            "ecoscore_grade": "not-applicable",
            "nutriments": {"energy-kcal_100g": 100},
        }
    )
    assert isinstance(result, ParsedFood)
    assert result.nutriscore_grade is None
    assert result.ecoscore_grade is None
