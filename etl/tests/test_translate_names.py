"""Traducción de nombres del catálogo (`etl/translate_names.py`).

Lo que se prueba es la barrera: un lote cuya respuesta no cuadra con la entrada se descarta
entero. Emparejar mal las traducciones renombraría un alimento con el nombre de otro, y eso
es peor que dejarlo en inglés — nadie se daría cuenta mirando la pantalla.
"""

import json

from etl.translate_names import MAX_NAME_CHARS, build_prompt, parse_response

NOMBRES = ["Beans, kidney, red, raw", "Cheese, cheddar", "Tacaud, cru"]
TRADUCIDOS = ["Alubia roja, cruda", "Queso cheddar", "Faneca, cruda"]


def respuesta(items) -> str:
    return json.dumps(items, ensure_ascii=False)


def test_una_respuesta_correcta_se_acepta():
    assert parse_response(respuesta(TRADUCIDOS), 3) == TRADUCIDOS


def test_se_acepta_envuelta_en_un_bloque_de_codigo():
    """El modelo a veces responde con markdown aunque se le pida que no."""
    assert parse_response(f"```json\n{respuesta(TRADUCIDOS)}\n```", 3) == TRADUCIDOS


def test_se_acepta_con_texto_alrededor():
    envuelto = f"Aquí tienes:\n{respuesta(TRADUCIDOS)}\nEspero que sirva."
    assert parse_response(envuelto, 3) == TRADUCIDOS


def test_si_faltan_o_sobran_elementos_se_descarta_el_lote():
    assert parse_response(respuesta(TRADUCIDOS[:2]), 3) is None
    assert parse_response(respuesta([*TRADUCIDOS, "De más"]), 3) is None


def test_una_respuesta_que_no_es_json_se_descarta():
    assert parse_response("No he podido traducirlos.", 3) is None
    assert parse_response("[esto no es json", 3) is None


def test_un_elemento_vacio_o_que_no_es_texto_descarta_el_lote():
    assert parse_response(respuesta(["Alubia roja", "", "Faneca"]), 3) is None
    assert parse_response(respuesta(["Alubia roja", 42, "Faneca"]), 3) is None


def test_un_nombre_desmesurado_descarta_el_lote():
    """Una explicación larga en vez de un nombre: no es una traducción."""
    largo = "x" * (MAX_NAME_CHARS + 1)
    assert parse_response(respuesta(["Alubia", largo, "Faneca"]), 3) is None


def test_el_prompt_lleva_los_nombres_y_cuántos_son():
    prompt = build_prompt(NOMBRES)
    assert "3" in prompt
    for nombre in NOMBRES:
        assert nombre in prompt
