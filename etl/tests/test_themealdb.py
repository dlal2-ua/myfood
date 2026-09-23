"""Pruebas de la lectura de un plato de TheMealDB."""

from etl.sources import themealdb

PLATO = {
    "idMeal": "52771",
    "strMeal": "Spicy Arrabiata Penne",
    "strCategory": "Vegetarian",
    "strArea": "Italian",
    "strInstructions": "Bring a large pot of water to a boil.",
    "strMealThumb": "https://www.themealdb.com/images/media/meals/x.jpg",
    "strIngredient1": "penne rigate",
    "strMeasure1": "1 pound",
    "strIngredient2": "olive oil",
    "strMeasure2": "1/4 cup",
    "strIngredient3": "",
    "strMeasure3": "",
}


def test_lee_el_plato_entero():
    recipe = themealdb.parse_meal(PLATO)
    assert recipe.source_id == "52771"
    assert recipe.name == "Spicy Arrabiata Penne"
    assert [i.name for i in recipe.ingredients] == ["penne rigate", "olive oil"]


def test_traduce_la_cocina_y_la_categoria():
    # Salen tal cual en los filtros de la pantalla, así que no pueden quedarse en inglés.
    recipe = themealdb.parse_meal(PLATO)
    assert recipe.cuisine == "Italiana"
    assert recipe.category == "Vegetariana"


def test_entiende_el_pais_y_el_gentilicio_como_la_misma_cocina():
    # TheMealDB escribe unas veces «French» y otras «France»: las dos son cocina francesa.
    assert themealdb.parse_meal({**PLATO, "strArea": "French"}).cuisine == "Francesa"
    assert themealdb.parse_meal({**PLATO, "strArea": "France"}).cuisine == "Francesa"


def test_una_cocina_desconocida_se_deja_en_ingles_y_se_apunta():
    themealdb.SIN_TRADUCIR.clear()
    recipe = themealdb.parse_meal({**PLATO, "strArea": "Martian"})
    assert recipe.cuisine == "Martian"
    assert "Martian" in themealdb.SIN_TRADUCIR


def test_sin_cocina_no_se_inventa_ninguna():
    # 190 de las 790 recetas vienen sin «strArea». Dejarlo vacío es la respuesta honrada.
    assert themealdb.parse_meal({**PLATO, "strArea": None}).cuisine is None


def test_descarta_lo_que_no_es_una_receta():
    assert themealdb.parse_meal({**PLATO, "strInstructions": ""}) is None
    assert themealdb.parse_meal({**PLATO, "strIngredient1": "", "strIngredient2": ""}) is None
