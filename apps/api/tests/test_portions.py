"""Raciones de un alimento (`domain/portions.py`).

Lo importante aquí no es la lista en sí, sino que los gramos coincidan con los que ya usa
`quantity_text` al interpretar el texto libre: el mismo huevo no puede pesar 60 g al escribir
«dos huevos» y otra cosa al elegir «huevo» en el desplegable.
"""

from myfood.domain.portions import BASE_PORTION, build_portions, default_grams
from myfood.domain.quantity_text import resolve_grams


def keys(portions) -> list[str]:
    return [p.key for p in portions]


def by_key(portions, key):
    return next(p for p in portions if p.key == key)


def test_gramos_siempre_es_una_opcion():
    """Sin gramos sueltos no se podría registrar nada que no encaje en una medida casera."""
    for name in ["Huevo", "Aceite de oliva", "Chuchería rarísima", "Leche entera"]:
        assert BASE_PORTION.key in keys(build_portions(name_es=name))


def test_un_huevo_pesa_lo_mismo_por_las_dos_vias():
    portions = build_portions(name_es="Huevo de gallina")
    unidad = by_key(portions, "unit_egg")
    assert unidad.label == "huevo"
    assert unidad.grams == resolve_grams("un huevo", None, food_name="Huevo de gallina")


def test_una_cucharada_de_aceite_pesa_lo_mismo_por_las_dos_vias():
    portions = build_portions(name_es="Aceite de oliva virgen extra")
    cucharada = by_key(portions, "cucharada")
    assert cucharada.grams == resolve_grams(
        "una cucharada", None, food_name="Aceite de oliva virgen extra"
    )
    # El aceite pesa menos por cucharada que un sólido: la tabla específica manda.
    assert cucharada.grams < 15


def test_la_racion_del_envase_va_primero_y_es_la_propuesta():
    portions = build_portions(
        name_es="Yogur natural", serving_size_g=125, serving_label="1 unidad"
    )
    assert portions[0].key == "serving"
    assert portions[0].label == "1 unidad"
    assert portions[0].grams == 125
    assert default_grams(portions) == 125


def test_sin_racion_del_envase_se_propone_la_unidad_natural():
    portions = build_portions(name_es="Huevo")
    assert portions[0].key == "unit_egg"
    assert default_grams(portions) == 60


def test_sin_nada_que_proponer_se_parte_de_cien_gramos():
    portions = build_portions(name_es="Mezcla sin clasificar")
    assert portions[0].key == BASE_PORTION.key
    assert default_grams(portions) == 100


def test_la_racion_del_envase_sustituye_a_la_unidad_no_se_suman():
    """Ofrecer «1 rebanada (30 g)» y «1 ración (45 g)» a la vez para el mismo pan son dos
    pesos distintos para la misma cosa."""
    portions = build_portions(name_es="Pan de molde integral", serving_size_g=45)
    assert "unit_bread" not in keys(portions)
    assert by_key(portions, "serving").grams == 45


def test_cada_grupo_ofrece_medidas_que_tienen_sentido():
    leche = keys(build_portions(name_es="Leche semidesnatada"))
    assert "vaso" in leche
    assert "cucharada" not in leche

    frutos = keys(build_portions(name_es="Almendras crudas"))
    assert "puñado" in frutos
    assert "vaso" not in frutos


def test_una_verdura_no_ofrece_medidas_de_liquido():
    portions = keys(build_portions(name_es="Calabacín"))
    assert "vaso" not in portions
    assert "unit_vegetable" in portions


def test_la_lista_no_se_hace_interminable():
    """Más de cinco opciones en un desplegable de móvil deja de ayudar."""
    for name in ["Leche entera", "Aceite de oliva", "Lentejas cocidas", "Copos de avena"]:
        assert len(build_portions(name_es=name, serving_size_g=30)) <= 5


def test_ninguna_racion_pesa_cero():
    for name in ["Huevo", "Leche", "Aceite", "Pan", "Almendras", "Lentejas", "Pollo"]:
        for portion in build_portions(name_es=name):
            assert portion.grams > 0


def test_una_racion_de_cien_gramos_no_se_ofrece_dos_veces():
    """Open Food Facts suele traer la ración como «100g», que es exactamente la opción de
    gramos sueltos: ofrecerla aparte salía como «100g (100 g)»."""
    portions = build_portions(name_es="Refresco de cola", serving_size_g=100, serving_label="100g")
    assert "serving" not in keys(portions)


def test_una_etiqueta_que_solo_repite_el_peso_se_sustituye_por_racion():
    portions = build_portions(name_es="Galletas", serving_size_g=30, serving_label="30 g")
    assert by_key(portions, "serving").label == "ración"
    assert by_key(portions, "serving").grams == 30


def test_una_etiqueta_que_dice_algo_se_respeta():
    portions = build_portions(name_es="Yogur", serving_size_g=125, serving_label="1 envase")
    assert by_key(portions, "serving").label == "1 envase"


def test_una_racion_de_cien_gramos_con_etiqueta_util_si_se_ofrece():
    portions = build_portions(name_es="Pizza", serving_size_g=100, serving_label="media pizza")
    assert by_key(portions, "serving").label == "media pizza"


def test_una_taza_de_cereales_pesa_lo_mismo_por_las_dos_vias():
    """Mismo pacto que con el huevo: el desplegable y el texto libre comparten tabla, así que
    la corrección por densidad tiene que verse en los dos."""
    taza = by_key(build_portions(name_es="Copos de avena"), "taza")
    assert taza.grams == resolve_grams("una taza", None, food_name="Copos de avena")
    assert taza.grams == 40.0


def test_una_cucharada_de_aceite_sigue_pesando_lo_mismo_por_las_dos_vias():
    cucharada = by_key(build_portions(name_es="Aceite de oliva virgen extra"), "cucharada")
    assert cucharada.grams == resolve_grams(
        "una cucharada", None, food_name="Aceite de oliva virgen extra"
    )
