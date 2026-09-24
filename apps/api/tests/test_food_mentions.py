from myfood.domain.food_mentions import split_into_food_mentions


def test_splits_on_y_con_and_commas():
    assert split_into_food_mentions("dos huevos fritos y una tostada con aceite") == [
        "huevos fritos",
        "tostada",
        "aceite",
    ]


def test_splits_on_comma_and_semicolon():
    assert split_into_food_mentions("arroz, pollo; brócoli") == ["arroz", "pollo", "brócoli"]


def test_strips_leading_digit_quantity():
    assert split_into_food_mentions("3 tostadas") == ["tostadas"]


def test_single_food_with_no_connectors_returns_itself():
    assert split_into_food_mentions("manzana") == ["manzana"]


def test_blank_text_returns_empty_list():
    assert split_into_food_mentions("   ") == []


def test_fragment_that_is_only_a_quantity_word_falls_back_to_itself():
    # "una" solo, sin nada detrás que quitar, no debe quedar vacío.
    assert split_into_food_mentions("una") == ["una"]


# --- arranques de frase y medidas: lo que Meilisearch no puede digerir ----------------------


def test_la_frase_del_usuario_se_parte_en_los_tres_alimentos():
    """El caso literal que falló: buscar «hoy he almorzado una porción de tortilla de patatas»
    devuelve cero, porque Meilisearch exige que TODOS los términos estén en el documento y
    ningún alimento se llama «almorzado»."""
    assert split_into_food_mentions(
        "hoy he almorzado una porción de tortilla de patatas, otra de ensaladilla "
        "y 4 trozos de pan"
    ) == ["tortilla de patatas", "ensaladilla", "pan"]


def test_se_quitan_las_medidas_de_delante():
    assert split_into_food_mentions("un vaso de leche") == ["leche"]
    assert split_into_food_mentions("dos rebanadas de pan integral") == ["pan integral"]
    assert split_into_food_mentions("un puñado de almendras") == ["almendras"]


def test_se_quita_en_que_comida_fue():
    assert split_into_food_mentions("para cenar merluza al horno") == ["merluza al horno"]
    assert split_into_food_mentions("de desayuno dos tostadas") == ["tostadas"]


def test_un_verbo_en_medio_de_la_frase_no_se_lleva_el_alimento_por_delante():
    """Con un comodín delante del verbo, «pollo que comí ayer» se quedaba en «ayer»."""
    assert split_into_food_mentions("pollo que comí ayer") == ["pollo que comí ayer"]


def test_un_fragmento_que_es_solo_una_medida_no_se_queda_vacio():
    assert split_into_food_mentions("una porción") == ["porción"]
