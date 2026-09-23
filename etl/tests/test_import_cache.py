"""Pruebas de la caché de traducciones del importador de recetas.

Existe por un susto concreto: la primera importación tardó cuarenta minutos, gastó un millón
de tokens y no escribió nada hasta el último segundo. Si se hubiera cortado, se habría perdido
todo lo pagado. Estas pruebas cubren que eso no vuelva a pasar.
"""

import json

from etl.import_themealdb import Cache


def test_una_cache_que_no_existe_arranca_vacia(tmp_path):
    cache = Cache(str(tmp_path / "no-esta.json"))
    assert len(cache) == 0
    assert cache.get("steps") == {}


def test_lo_guardado_se_lee_en_la_siguiente_ejecucion(tmp_path):
    ruta = str(tmp_path / "cache.json")
    Cache(ruta).update("titles", {"Beef Wellington": "Solomillo Wellington"})
    assert Cache(ruta).get("titles")["Beef Wellington"] == "Solomillo Wellington"


def test_cada_lote_se_escribe_al_momento(tmp_path):
    # Lo que hace que una importación cortada no cueste dos veces: el fichero está en disco
    # antes de pedir el lote siguiente, no al terminar.
    ruta = tmp_path / "cache.json"
    cache = Cache(str(ruta))
    cache.update("steps", {"Boil it": "Hervir"})
    assert json.loads(ruta.read_text(encoding="utf-8"))["steps"] == {"Boil it": "Hervir"}


def test_un_fichero_roto_no_tumba_la_importacion(tmp_path):
    # Un corte justo durante la escritura no puede impedir volver a importar: se empieza de
    # cero, que es lento, pero no falla.
    ruta = tmp_path / "cache.json"
    ruta.write_text('{"titles": {"a": ', encoding="utf-8")
    assert len(Cache(str(ruta))) == 0


def test_se_ignora_lo_que_no_sea_texto(tmp_path):
    ruta = tmp_path / "cache.json"
    ruta.write_text(json.dumps({"titles": {"a": "A", "b": 7}, "otra": {"x": "y"}}), "utf-8")
    cache = Cache(str(ruta))
    assert cache.get("titles") == {"a": "A"}
    assert "otra" not in cache.data


def test_no_deja_el_temporal_tirado(tmp_path):
    cache = Cache(str(tmp_path / "cache.json"))
    cache.update("ingredients", {"onion": "cebolla"})
    assert [f.name for f in tmp_path.iterdir()] == ["cache.json"]
