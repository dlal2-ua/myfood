"""Cantidades inglesas de TheMealDB a gramos (`etl/sources/measures_en.py`).

Esta capa NO decide cuánto pesa una taza: traduce la medida al término español y deja que lo
resuelva la tabla del dominio. Lo que se prueba aquí son las fracciones («1 1/2») y las
unidades de peso, que es lo que el texto libre en español nunca trae.
"""

import pytest

from etl.sources.measures_en import parse_amount, to_spanish_quantity


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("2", 2.0),
        ("2.5", 2.5),
        ("3/4", 0.75),
        ("1 1/2", 1.5),
        ("½", 0.5),
        ("1 ½", 1.5),
        ("1/0", 1.0),  # denominador cero: se queda con lo que pueda, no revienta
    ],
)
def test_se_entienden_las_fracciones(texto, esperado):
    assert parse_amount(texto) == pytest.approx(esperado)


def test_sin_numero_no_hay_cantidad():
    assert parse_amount("to taste") is None
    assert parse_amount("") is None


def test_las_unidades_de_peso_se_convierten_a_gramos():
    assert to_spanish_quantity("2 oz") == "56.7 g"
    assert to_spanish_quantity("1 lb") == "453.6 g"
    assert to_spanish_quantity("250 g") == "250 g"
    assert to_spanish_quantity("1 kg") == "1000 g"


def test_las_medidas_caseras_se_traducen_sin_poner_gramos():
    """El peso lo decide la tabla del dominio, no esta capa: aquí solo se traduce la palabra."""
    assert to_spanish_quantity("3/4 cup") == "0.75 taza"
    assert to_spanish_quantity("1 tbsp") == "1 cucharada"
    assert to_spanish_quantity("2 teaspoons") == "2 cucharadita"
    assert to_spanish_quantity("a pinch") == "1 pizca"


def test_lo_que_se_cuenta_por_piezas_conocidas_sale_en_gramos():
    assert to_spanish_quantity("2 cloves") == "10 g"
    assert to_spanish_quantity("4 rashers") == "100 g"


def test_un_recuento_sin_medida_deja_que_lo_resuelva_el_dominio():
    """«2 onions»: cuánto pesa una cebolla lo sabe `quantity_text` por su grupo."""
    assert to_spanish_quantity("2") == "2"
    assert to_spanish_quantity("1 large") == "1"


def test_una_cantidad_vacia_o_sin_numero_no_inventa_nada():
    assert to_spanish_quantity("") == ""
    assert to_spanish_quantity("to serve") == ""


def test_una_cantidad_real_de_la_api():
    assert to_spanish_quantity("3/4 cup") == "0.75 taza"
    assert to_spanish_quantity("1/2 teaspoon") == "0.5 cucharadita"
