"""Tests de transformación CIQUAL con muestras reales (documento 2, sección 16)."""

import json
from pathlib import Path

from etl.db import ParsedFood
from etl.rejected import Rejection
from etl.sources.ciqual import _parse_number, parse_food

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _load_fixture() -> list[dict]:
    with (FIXTURES / "ciqual_sample.json").open(encoding="utf-8") as f:
        return json.load(f)["rows"]


def test_parse_real_food_maps_macros():
    row = _load_fixture()[0]
    assert row["alim_nom_fr"] == "Taboulé ou Salade de couscous, préemballé"

    result = parse_food(row)

    assert isinstance(result, ParsedFood)
    assert result.source == "ciqual"
    assert result.name_es == "Taboulé ou Salade de couscous, préemballé"
    assert result.kcal_100g == 179
    assert result.quality_rank == 3
    assert result.license == "Licence Ouverte (Etalab)"


def test_parse_second_real_food():
    row = _load_fixture()[1]
    result = parse_food(row)
    assert isinstance(result, ParsedFood)
    assert result.kcal_100g == 130


def test_food_without_kcal_is_rejected():
    row = _load_fixture()[2]  # "Dessert (aliment moyen)" — fila de cabecera de grupo, sin datos
    result = parse_food(row)
    assert isinstance(result, Rejection)
    assert result.reason == "MISSING_KCAL"


def test_parse_number_handles_missing_marker():
    assert _parse_number("-") is None


def test_parse_number_handles_traces():
    assert _parse_number("traces") is None
    assert _parse_number("Traces") is None


def test_parse_number_uses_below_detection_limit_literally():
    # "< 0,1" -> se usa 0.1 literal, tal cual lo reporta la fuente (no se inventa).
    assert _parse_number("< 0,1") == 0.1


def test_parse_number_converts_comma_decimal():
    assert _parse_number("29,9") == 29.9


def test_parse_number_handles_empty_string():
    assert _parse_number("") is None


def test_missing_source_id_is_rejected():
    result = parse_food({"alim_code": "", "alim_nom_fr": "Sin código"})
    assert isinstance(result, Rejection)
    assert result.reason == "MISSING_SOURCE_ID"


def test_missing_name_is_rejected():
    result = parse_food({"alim_code": "12345", "alim_nom_fr": ""})
    assert isinstance(result, Rejection)
    assert result.reason == "MISSING_NAME"


def test_macros_exceeding_100g_is_rejected():
    row = {
        "alim_code": "99999",
        "alim_nom_fr": "Macros imposibles",
        "Energie, Règlement UE N° 1169/2011 (kcal/100 g)": "400",
        "Protéines, N x facteur de Jones (g/100 g)": "60",
        "Lipides (g/100 g)": "30",
        "Glucides (g/100 g)": "30",
    }
    result = parse_food(row)
    assert isinstance(result, Rejection)
    assert result.reason == "MACROS_EXCEED_100G"


def test_salt_comes_directly_no_conversion_needed():
    row = {
        "alim_code": "1",
        "alim_nom_fr": "Con sal",
        "Energie, Règlement UE N° 1169/2011 (kcal/100 g)": "100",
        "Sel chlorure de sodium (g/100 g)": "1,2",
    }
    result = parse_food(row)
    assert isinstance(result, ParsedFood)
    assert result.salt_100g == 1.2
