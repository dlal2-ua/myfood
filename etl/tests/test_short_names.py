"""Nombres cortos del catálogo (`etl/short_names.py`).

Lo que se prueba es la barrera, igual que en la traducción: un lote cuya respuesta no cuadra
con la entrada se descarta entero. Emparejar mal los nombres le pondría a un alimento el nombre
corto de otro, y en una lista nadie se daría cuenta — es peor que dejarlo largo.
"""

import json

from etl.short_names import MAX_SHORT_CHARS, build_prompt, parse_response

LARGOS = [
    "Huevo, entero, crudo, congelado, salado, pasteurizado",
    "Pollo, pechuga, con piel, crudo",
    "Arroz blanco, grano largo, regular, crudo, enriquecido",
]
CORTOS = [
    "Huevo entero congelado",
    "Pechuga de pollo con piel, cruda",
    "Arroz blanco de grano largo",
]


def respuesta(items) -> str:
    return json.dumps(items, ensure_ascii=False)


def test_una_respuesta_correcta_se_acepta():
    assert parse_response(respuesta(CORTOS), len(LARGOS)) == CORTOS


def test_un_lote_con_menos_nombres_de_los_pedidos_se_descarta_entero():
    assert parse_response(respuesta(CORTOS[:2]), 3) is None


def test_un_nombre_mas_largo_que_el_tope_descarta_el_lote():
    """Un «nombre corto» que no cabe en una línea no es un nombre corto."""
    demasiado = ["x" * (MAX_SHORT_CHARS + 1), *CORTOS[1:]]
    assert parse_response(respuesta(demasiado), 3) is None


def test_un_nombre_vacio_descarta_el_lote():
    assert parse_response(respuesta(["", *CORTOS[1:]]), 3) is None


def test_algo_que_no_es_una_lista_de_textos_se_descarta():
    assert parse_response(respuesta([1, 2, 3]), 3) is None
    assert parse_response("lo siento, no puedo", 3) is None
    assert parse_response('{"nombres": []}', 3) is None


def test_se_acepta_envuelto_en_markdown():
    """El modelo a veces contesta con el JSON dentro de un bloque de código."""
    assert parse_response(f"```json\n{respuesta(CORTOS)}\n```", 3) == CORTOS


def test_los_espacios_de_sobra_se_limpian():
    assert parse_response(respuesta(["  Huevo   entero  "]), 1) == ["Huevo entero"]


def test_el_prompt_lleva_los_nombres_y_cuántos_son():
    prompt = build_prompt(LARGOS)
    assert "3 nombres" in prompt
    assert "Pollo, pechuga, con piel, crudo" in prompt
