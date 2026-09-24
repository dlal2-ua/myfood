from myfood.domain.quantity_text import (
    DEFAULT_SERVING_GRAMS,
    compose_quantity_text,
    resolve_grams,
)


def test_explicit_grams_wins_over_serving_size():
    assert resolve_grams("200 g", serving_size_g=50) == 200.0
    assert resolve_grams("150gr", serving_size_g=None) == 150.0
    assert resolve_grams("250 gramos", serving_size_g=50) == 250.0


def test_digit_quantity_multiplies_serving_size():
    assert resolve_grams("2", serving_size_g=60) == 120.0
    assert resolve_grams("3 unidades", serving_size_g=60) == 180.0


def test_spanish_number_words_multiply_serving_size():
    assert resolve_grams("dos huevos", serving_size_g=60) == 120.0
    assert resolve_grams("una tostada", serving_size_g=40) == 40.0
    assert resolve_grams("tres piezas", serving_size_g=30) == 90.0


def test_unrecognized_text_defaults_to_one_unit():
    assert resolve_grams("lo de siempre", serving_size_g=80) == 80.0
    assert resolve_grams("un poco", serving_size_g=80) == 80.0


def test_la_racion_del_envase_manda_sobre_la_del_grupo():
    """Si la etiqueta dice que una ración son 80 g, eso es «una ración» para ESE producto."""
    assert resolve_grams("una ración", serving_size_g=80) == 80.0
    assert resolve_grams("ración habitual", serving_size_g=80) == 80.0
    assert resolve_grams("dos raciones", serving_size_g=80) == 160.0
    # Y el tamaño relativo sigue aplicándose encima.
    assert resolve_grams("una ración generosa", serving_size_g=80) == 112.0


def test_missing_serving_size_falls_back_to_the_group_portion():
    """Sin ración de envase y sin nombre no hay por dónde clasificar: una ración cualquiera
    ronda los 150 g, no los 100 g de una unidad suelta."""
    assert resolve_grams("una ración", serving_size_g=None) == 150.0
    assert resolve_grams("dos raciones", serving_size_g=None) == 300.0
    assert resolve_grams("dos", serving_size_g=None) == DEFAULT_SERVING_GRAMS * 2


def test_word_boundary_does_not_match_substrings():
    # "una" no debe disparar el valor de "un" como substring.
    assert resolve_grams("una manzana", serving_size_g=100) == 100.0


# --- pesos de una unidad por grupo, medidas caseras y unidades explícitas (Fase 8) --------------

import pytest  # noqa: E402


@pytest.mark.parametrize(
    ("text", "name", "category", "expected"),
    [
        ("6 huevos", "Huevo de gallina, cocido", None, 360.0),  # antes 600 g
        ("dos huevos fritos", "Huevo de gallina, frito", None, 120.0),
        ("una manzana", "Manzana, con piel, cruda", "Frutas y derivados", 130.0),
        ("dos tostadas", "Pan tostado", "toasts", 60.0),  # antes 200 g
        ("un yogur", "Yogur natural", "plain yogurts", 125.0),
        ("una loncha", "Jamón cocido extra", "white hams", 20.0),
        ("un filete", "Ternera, solomillo, a la plancha", "Cárnicos y derivados", 150.0),
        ("un plato", "Lentejas, cocidas", None, 250.0),
    ],
)
def test_a_unit_weighs_what_its_food_group_typically_weighs(text, name, category, expected):
    assert resolve_grams(text, None, food_name=name, category=category) == expected


def test_the_label_serving_still_beats_the_group_default():
    assert resolve_grams("dos", 45, food_name="Huevo de gallina, cocido") == 90.0


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("una cucharada", 15.0),
        ("2 cucharadas", 30.0),
        ("una cucharadita", 5.0),
        ("un vaso", 200.0),
        ("dos vasos", 400.0),
        ("una taza", 250.0),
        ("un puñado", 30.0),
        ("media taza", 125.0),
    ],
)
def test_home_measures(text, expected):
    assert resolve_grams(text, serving_size_g=None, food_name="Leche desnatada") == expected


def test_a_spoonful_of_oil_weighs_less_than_one_of_powder():
    assert resolve_grams("una cucharada", None, food_name="Aceite de oliva virgen extra") == 10.0
    assert resolve_grams("una cucharada", None, food_name="Cacao en polvo") == 15.0


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1 kg", 1000.0),
        ("1,5 kg", 1500.0),
        ("250 ml", 250.0),
        ("medio litro", 500.0),
        ("un kilo", 1000.0),
        ("medio kilo", 500.0),
        ("2 l", 2000.0),
    ],
)
def test_explicit_weights_and_volumes(text, expected):
    assert resolve_grams(text, serving_size_g=30) == expected


def test_half_a_unit():
    assert resolve_grams("media manzana", None, food_name="Manzana", category=None) == 65.0


def test_an_unknown_food_still_falls_back_to_the_default_portion():
    assert resolve_grams("dos", None, food_name="Xyzzy") == DEFAULT_SERVING_GRAMS * 2


# --- porción / ración / trozo: dependen del alimento, no son gramos fijos ------------------


@pytest.mark.parametrize(
    ("text", "food", "expected"),
    [
        # El ejemplo literal del usuario: antes los tres caían al fallback de 100 g por unidad.
        ("una porción", "Tortilla española de patatas", 250.0),
        ("una porción", "Ensaladilla rusa", 250.0),
        ("4 trozos", "Pan, de trigo blanco", 160.0),
        ("una ración", "Lentejas guisadas", 200.0),
        ("un trozo", "Queso manchego curado", 40.0),
        ("una ración", "Merluza a la plancha", 150.0),
        ("media porción", "Tarta de queso", 40.0),
    ],
)
def test_una_porcion_pesa_lo_que_pesa_una_porcion_de_ESE_alimento(text, food, expected):
    assert resolve_grams(text, None, food_name=food) == expected


def test_una_porcion_de_un_alimento_desconocido_no_se_queda_en_cien_gramos():
    """100 g era menos de la mitad de cualquier ración real: es el valor que hacía que las
    calorías del día no cuadrasen al registrar platos caseros."""
    assert resolve_grams("una porción", None, food_name="Xyzzy") == 150.0


@pytest.mark.parametrize(
    ("text", "food", "expected"),
    [
        ("dos rebanadas", "Pan de molde blanco", 60.0),
        ("un filete", "Pechuga de pollo cruda", 150.0),
        ("tres lonchas", "Jamón cocido", 60.0),
        ("una pieza", "Manzana", 130.0),
    ],
)
def test_las_unidades_con_nombre_pesan_lo_mismo_que_en_el_desplegable(text, food, expected):
    """«dos rebanadas» tiene que dar lo mismo que elegir «rebanada» en el desplegable: si no,
    el mismo pan pesa distinto según por dónde se registre."""
    assert resolve_grams(text, None, food_name=food) == expected


# --- densidad: una taza de cereales no pesa lo que una taza de guiso ------------------------


@pytest.mark.parametrize(
    ("text", "food", "expected"),
    [
        ("un bol", "Cereales de desayuno con miel", 50.0),
        ("una taza", "Copos de avena", 40.0),
        ("un bol", "Lentejas guisadas", 350.0),
        ("una taza", "Almendras crudas", 120.0),
    ],
)
def test_las_medidas_de_volumen_tienen_en_cuenta_lo_hueco_que_es_el_alimento(text, food, expected):
    """Sin esto, «un bol de cereales» salían 350 g — unas 1.300 kcal."""
    assert resolve_grams(text, None, food_name=food) == expected


# --- tamaño relativo ------------------------------------------------------------------------


def test_el_tamano_multiplica_lo_que_digan_las_tablas():
    normal = resolve_grams("un plato", None, food_name="Macarrones cocidos")
    assert resolve_grams("un plato grande", None, food_name="Macarrones cocidos") == round(
        normal * 1.4, 1
    )
    assert resolve_grams("un plato pequeño", None, food_name="Macarrones cocidos") == round(
        normal * 0.7, 1
    )


# --- lo que dijo el usuario + lo que entendió el modelo -------------------------------------


def test_el_tipo_de_cantidad_del_modelo_se_junta_con_lo_que_dijo_el_usuario():
    """El modelo devuelve «dos» y, aparte, que son rebanadas. Sin juntarlos, «dos» a secas caía
    al peso de una unidad genérica."""
    assert compose_quantity_text("dos", "rebanada", None) == "dos rebanada"
    assert resolve_grams(
        compose_quantity_text("dos", "rebanada", None), None, food_name="Pan de molde"
    ) == 60.0


def test_el_tamano_mediano_no_ensucia_el_texto():
    assert compose_quantity_text("un plato", "plato", "mediano") == "un plato plato"
    assert compose_quantity_text("un plato", "plato", "grande") == "un plato plato grande"


def test_gramos_no_se_repite_como_tipo():
    assert compose_quantity_text("200 g", "gramos", None) == "200 g"
