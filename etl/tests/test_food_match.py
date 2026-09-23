"""Pruebas del emparejado de ingredientes con el catálogo.

Los casos vienen de los 86 ingredientes que la primera importación de TheMealDB dejó sin
equivalente: casi todos eran plurales o acentos, no alimentos que falten de verdad.
"""

from etl.transform.food_match import (
    build_index,
    match,
    name_variants,
    normalize,
    singular_forms,
)

# Un catálogo de mentira con la misma forma que el de verdad: ya ordenado por preferencia,
# con el nombre bueno antes que el rebuscado.
CATALOGO = [
    ("1", "Cebolla, cruda", "verduras"),
    ("2", "Cebolla deshidratada en polvo, enriquecida", "verduras"),
    ("3", "Berenjena, cruda", "verduras"),
    ("4", "Calabacín, crudo", "verduras"),
    ("5", "Boniato, crudo", "verduras"),
    ("6", "Tomate, crudo", "verduras"),
    ("7", "Nuez", "frutos secos"),
    ("8", "Pechuga de pollo, cruda", "carnes"),
    ("9", "Aceite de oliva virgen extra", "grasas"),
    ("10", "Caña de azúcar", "azúcares"),
    ("11", "Cana blanca", "otros"),
]


def indice():
    return build_index(CATALOGO)


def test_normalize_quita_acentos_pero_conserva_la_ñ():
    assert normalize("Calabacín, crudo") == "calabacin crudo"
    assert normalize("Caña de azúcar") == "caña de azucar"


def test_normalize_no_confunde_caña_con_cana():
    # La tilde no distingue alimentos, la eñe sí: si se quitara, «caña» encontraría «cana».
    assert normalize("caña") != normalize("cana")


def test_singular_forms_ofrece_las_dos_lecturas_del_plural():
    assert "calabacin" in singular_forms("calabacines")
    assert "tomate" in singular_forms("tomates")
    assert "nuez" in singular_forms("nueces")


def test_singular_forms_deja_en_paz_lo_que_es_corto():
    assert singular_forms("ajo") == []
    assert singular_forms("sal") == []


def test_plural_encuentra_el_singular_del_catalogo():
    idx = indice()
    assert match("Berenjenas", idx).id == "3"
    assert match("Boniatos", idx).id == "5"
    assert match("Calabacines", idx).id == "4"
    assert match("Nueces", idx).id == "7"


def test_prefiere_el_alimento_corriente_al_rebuscado():
    # «Cebolla, cruda» antes que «Cebolla deshidratada en polvo»: los dos contienen «cebolla».
    assert match("Cebollas", indice()).id == "1"


def test_empareja_aunque_cambie_el_orden_de_las_palabras():
    assert match("pollo pechuga", indice()).id == "8"


def test_cae_en_la_cabeza_cuando_la_frase_entera_no_existe():
    # No hay «aceite de oliva suave», pero el aceite de oliva sigue siendo la respuesta.
    assert match("aceite de oliva suave para freir", indice()).id == "9"


def test_devuelve_none_cuando_no_hay_nada_parecido():
    assert match("Ackee", indice()) is None
    assert match("Callaloo", indice()) is None


def test_nombre_vacio_no_revienta():
    assert match("", indice()) is None
    assert match("   ", indice()) is None
    assert name_variants("...") == []


def test_no_empareja_por_una_palabra_de_relleno():
    # «de» sola no puede traer «Aceite de oliva»: sin palabras útiles no hay emparejado.
    assert match("de", indice()) is None


# El catálogo de verdad casi nunca tiene el alimento «a secas»: tiene diez versiones suyas, y
# elegir mal cambia las calorías de la receta. Estos casos son los que decidieron el criterio.
CATALOGO_REAL = [
    ("20", "Salmón ahumado", "pescados"),
    ("21", "Salmón, crudo, salvaje", "pescados"),
    ("22", "Garbanzo, seco, crudo", "legumbres"),
    ("23", "Garbanzos, semillas maduras, crudos", "legumbres"),
    ("24", "Pechuga de pollo, enrollada, asada al horno", "carnes"),
    ("25", "Pollo, pechuga, con piel, crudo", "carnes"),
    ("26", "Caldo de pollo, deshidratado", "otros"),
    ("27", "Caldo de pescado", "otros"),
    ("28", "Harina de mijo", "cereales"),
    ("29", "Harina de trigo, blanca, panadería", "cereales"),
    ("30", "Leche de coco", "bebidas"),
    ("31", "Leche entera, UHT", "lácteos"),
]


def real():
    return build_index(CATALOGO_REAL)


def test_prefiere_el_crudo_al_ahumado():
    # El ahumado tiene el nombre más corto y aun así es otro alimento: 117 kcal contra 208.
    assert match("Salmón", real()).id == "21"


def test_un_nombre_corto_procesado_no_gana_a_uno_largo_y_crudo():
    assert match("Garbanzos", real()).id == "23"


def test_no_se_queda_en_la_pechuga_asada_habiendo_pollo_crudo():
    assert match("Pechuga de pollo", real()).id == "25"


def test_un_deshidratado_es_mejor_que_cambiar_de_alimento():
    # No hay caldo de pollo sin deshidratar: vale más ese que un caldo de pescado.
    assert match("Caldo de pollo", real()).id == "26"


def test_la_palabra_suelta_tiene_un_significado_por_defecto():
    # Sin esto «harina» cae en la de mijo y «leche» en la de coco, por ser nombres más cortos.
    assert match("Harina", real()).id == "29"
    assert match("Leche", real()).id == "31"


def test_el_alias_no_impide_encontrar_lo_que_si_esta():
    # «Leche de coco» pedida por su nombre sigue siendo leche de coco.
    assert match("Leche de coco", real()).id == "30"
