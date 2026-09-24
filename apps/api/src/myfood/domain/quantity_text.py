"""Heurística para convertir la cantidad en texto libre que dio el LLM (`approx_quantity_text`,
sección 10.8 — la IA nunca calcula gramos, R1) en un gramaje por defecto real.

Deliberadamente simple, no es NLP de cantidades: es un punto de partida razonable que el usuario
siempre revisa y corrige antes de confirmar (sección 10.8: «el usuario revisa, ajusta gramos… y
confirma»), nunca el valor final que se guarda sin esa revisión. Reconoce, por este orden:

1. un peso o volumen explícito («200 g», «1 kg», «250 ml», «medio litro»), que se usa tal cual;
2. una medida casera de peso fijo (cucharada, vaso, taza, plato, bol, puñado…) por la cantidad;
3. una porción, ración o trozo, cuyo peso depende del alimento: una porción de tortilla son 250 g
   y una de queso 40 g, así que salen de `PORTION_GRAMS_BY_GROUP` y no de una tabla fija. Antes
   no se reconocían en absoluto y «una porción de tortilla de patatas» caía al paso 4 con 100 g;
4. una cantidad de unidades («2», «dos», «media», «dos rebanadas», «un filete») por el peso de una
   unidad: la ración del envase si el alimento la tiene y, si no, el peso típico de una unidad de
   su grupo alimentario (un huevo pesa ~60 g, una rebanada de pan ~30 g, una pieza de fruta
   ~130 g…). Antes todo lo desconocido pesaba 100 g por unidad y «6 huevos» salía como 600 g.

Sobre el resultado se aplica el tamaño relativo si se menciona («un plato grande» ×1,4).
"""

from __future__ import annotations

import re

from myfood.domain import food_groups as fg

DEFAULT_SERVING_GRAMS = 100.0

_NUMBER_WORDS = {
    "un": 1,
    "uno": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "medio": 0.5,
    "media": 0.5,
}

_NUMBER = r"\d+(?:[.,]\d+)?"

# Un peso o volumen explícito se usa TAL CUAL en vez de multiplicar por la ración del alimento.
_EXPLICIT_RE = re.compile(
    rf"({_NUMBER})\s*(kilos?|kg|litros?|l|ml|mililitros?|gramos?|gr|g)\b", re.IGNORECASE
)
_WORD_QUANTITY_RE = re.compile(r"\b(medio|media|un|una)\s+(kilo|litro)s?\b", re.IGNORECASE)
_DIGIT_QUANTITY_RE = re.compile(_NUMBER)

_UNIT_TO_GRAMS = {
    "kilo": 1000.0, "kilos": 1000.0, "kg": 1000.0,
    "litro": 1000.0, "litros": 1000.0, "l": 1000.0,
    "ml": 1.0, "mililitro": 1.0, "mililitros": 1.0,
    "g": 1.0, "gr": 1.0, "gramo": 1.0, "gramos": 1.0,
}  # fmt: skip

# Medidas caseras (gramos por medida) — públicas: `domain/portions.py` ofrece las mismas al
# usuario, y el mismo alimento no puede pesar distinto según por dónde se registre.
# Medidas caseras (gramos por medida) y su peso cuando el alimento es una grasa de cocina, que
# pesa menos por cucharada que un polvo o un azúcar.
MEASURES = {
    "cucharadita": 5.0,
    "cucharada": 15.0,
    "chorrito": 5.0,
    "vaso": 200.0,
    "taza": 250.0,
    "tazon": 300.0,
    "copa": 150.0,
    "plato": 250.0,
    "bol": 350.0,
    "cazo": 90.0,
    "puñado": 30.0,
    "puñados": 30.0,
    "pizca": 1.0,
    "lata": 80.0,
}
_MEASURE_ALIASES = {"cucharadas": "cucharada", "cucharaditas": "cucharadita", "vasos": "vaso",
                    "tazas": "taza", "tazones": "tazon", "copas": "copa", "platos": "plato",
                    "latas": "lata", "tazón": "tazon", "boles": "bol", "cuenco": "bol",
                    "cuencos": "bol", "cazos": "cazo", "cucharon": "cazo", "cucharón": "cazo",
                    "cucharones": "cazo"}  # fmt: skip
OIL_MEASURES = {"cucharada": 10.0, "cucharadita": 4.0, "chorrito": 5.0}

# Un bol lleno de cereales de desayuno pesa unos 50 g; el mismo bol de guiso, 350. Las medidas
# de volumen sin densidad daban «un bol de cereales» = 350 g ≈ 1.300 kcal, que es justo el tipo
# de error que hace que las calorías del día no cuadren. Solo se corrigen los grupos que son
# claramente huecos o claramente densos; el resto usa `MEASURES`.
MEASURE_OVERRIDES_BY_GROUP: dict[str, dict[str, float]] = {
    fg.OIL_FAT: OIL_MEASURES,
    fg.CEREAL: {"vaso": 35.0, "taza": 40.0, "tazon": 50.0, "bol": 50.0, "plato": 50.0},
    fg.SNACK: {"vaso": 30.0, "taza": 40.0, "tazon": 50.0, "bol": 50.0, "plato": 60.0},
    fg.NUTS: {"vaso": 100.0, "taza": 120.0, "tazon": 150.0, "bol": 150.0, "plato": 120.0},
}


def measure_grams(measure: str, group: str | None) -> float:
    """Lo que pesa UNA de esas medidas para este grupo de alimento. Pública: el desplegable de
    raciones (`domain/portions.py`) tiene que dar el mismo peso que el texto libre."""
    override = MEASURE_OVERRIDES_BY_GROUP.get(group or "")
    if override and measure in override:
        return override[measure]
    return MEASURES[measure]

# «Una PORCIÓN de tortilla» y «una porción de queso» no pesan lo mismo, así que estas medidas
# no pueden tener gramos fijos como las de arriba: dependen del alimento, igual que las
# unidades. Antes no se reconocían en absoluto y «una porción de tortilla de patatas» caía al
# fallback de 100 g por unidad, que es menos de la mitad de una ración real.
PORTION_MEASURES = ("porcion", "racion", "trozo")
_PORTION_ALIASES = {"porción": "porcion", "porciones": "porcion", "porcions": "porcion",
                    "ración": "racion", "raciones": "racion", "racion": "racion",
                    "trozos": "trozo", "cacho": "trozo", "cachos": "trozo",
                    "pedazo": "trozo", "pedazos": "trozo"}  # fmt: skip

PORTION_GRAMS_BY_GROUP = {
    fg.PREPARED: 250.0,   # tortilla, ensaladilla, lasaña: un plato de verdad
    fg.LEGUME: 200.0,
    fg.GRAIN: 200.0,
    fg.MEAT: 150.0,
    fg.FISH: 150.0,
    fg.VEGETABLE: 150.0,
    fg.DAIRY: 125.0,
    fg.SWEET: 80.0,
    fg.CHEESE: 40.0,
    fg.BREAD: 40.0,       # un trozo de barra, más que una rebanada de molde
    fg.PROCESSED_MEAT: 30.0,
    fg.CEREAL: 40.0,
    fg.NUTS: 30.0,
    fg.FRUIT: 80.0,       # un gajo de melón, no la pieza entera
    fg.SNACK: 30.0,
}
DEFAULT_PORTION_GRAMS = 150.0

# Nombres de UNA unidad que `domain/portions.py` ya ofrece en el desplegable. Sin esto, el
# mismo alimento pesaba distinto según se registrara escribiendo («una rebanada» → 100 g) o
# eligiendo del desplegable («rebanada» → 30 g).
UNIT_WORDS = ("unidad", "pieza", "huevo", "rebanada", "loncha", "filete")
_UNIT_ALIASES = {"unidades": "unidad", "piezas": "pieza", "huevos": "huevo",
                 "rebanadas": "rebanada", "lonchas": "loncha", "filetes": "filete"}  # fmt: skip

# «Media ración», «un plato grande»: el tamaño relativo multiplica lo que salga de las tablas.
SIZE_FACTORS = {"pequeno": 0.7, "pequeño": 0.7, "pequena": 0.7, "pequeña": 0.7,
                "mediano": 1.0, "mediana": 1.0, "normal": 1.0,
                "grande": 1.4, "generoso": 1.4, "generosa": 1.4, "abundante": 1.4}  # fmt: skip

# Peso típico de UNA unidad de cada grupo cuando el catálogo no trae la ración.
UNIT_GRAMS_BY_GROUP = {
    fg.EGG: 60.0,
    fg.FRUIT: 130.0,
    fg.BREAD: 30.0,
    fg.DAIRY: 125.0,
    fg.CHEESE: 30.0,
    fg.PROCESSED_MEAT: 20.0,
    fg.MEAT: 150.0,
    fg.FISH: 150.0,
    fg.VEGETABLE: 100.0,
    fg.LEGUME: 150.0,
    fg.GRAIN: 150.0,
    fg.CEREAL: 40.0,
    fg.NUTS: 30.0,
    fg.OIL_FAT: 10.0,
}


def _normalize(text: str) -> str:
    return text.strip().lower()


def _parse_number(raw: str) -> float:
    return float(raw.replace(",", "."))


def _count(text: str) -> float:
    """Cuántas unidades o medidas se piden («2», «tres», «media»); 1 si no se dice."""
    digit_match = _DIGIT_QUANTITY_RE.search(text)
    if digit_match:
        return _parse_number(digit_match.group(0))
    for word, value in _NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", text):
            return float(value)
    return 1.0


def _unit_grams(serving_size_g: float | None, food_name: str | None, category: str | None) -> float:
    if serving_size_g:
        return float(serving_size_g)
    if food_name:
        group = fg.classify_food(food_name, category)
        if group in UNIT_GRAMS_BY_GROUP:
            return UNIT_GRAMS_BY_GROUP[group]
    return DEFAULT_SERVING_GRAMS


def _size_factor(text: str) -> float:
    """«Un plato grande» pesa más que «un plato»; multiplica lo que salga de las tablas."""
    for word in re.findall(r"[a-záéíóúñ]+", text):
        if word in SIZE_FACTORS:
            return SIZE_FACTORS[word]
    return 1.0


def portion_grams(
    serving_size_g: float | None, food_name: str | None, category: str | None
) -> float:
    """Lo que pesa UNA porción/ración/trozo de este alimento.

    La ración del envase manda sobre la del grupo: si la etiqueta dice que una ración son 80 g,
    eso es lo que significa «una ración» para ese producto. Solo cuando no la hay se recurre al
    peso típico del grupo."""
    if serving_size_g:
        return float(serving_size_g)
    group = fg.classify_food(food_name, category) if food_name else None
    return PORTION_GRAMS_BY_GROUP.get(group or "", DEFAULT_PORTION_GRAMS)


def compose_quantity_text(
    approx_quantity_text: str, tipo_cantidad: str | None, tamano: str | None
) -> str:
    """Junta lo que dijo el usuario con lo que el modelo entendió.

    El modelo devuelve la cantidad como la dijo el usuario («dos», «4 trozos») y, aparte, en qué
    unidad la ha contado y si era grande o pequeña. Aquí se pegan las tres en una sola frase,
    que es lo que `resolve_grams` sabe leer: «dos» + «rebanada» → «dos rebanada» → 2 × 30 g. Sin
    esto, «dos» a secas caía al peso de una unidad genérica.
    """
    parts = [approx_quantity_text or ""]
    if tipo_cantidad and tipo_cantidad != "gramos":
        parts.append(tipo_cantidad)
    if tamano and tamano != "mediano":
        parts.append(tamano)
    return " ".join(part for part in parts if part).strip()


def resolve_grams(
    approx_quantity_text: str,
    serving_size_g: float | None,
    *,
    food_name: str | None = None,
    category: str | None = None,
) -> float:
    """Gramaje por defecto de un elemento de Smart Log, del chat, de un ticket o de una receta
    importada. `food_name`/`category` permiten estimar el peso de una unidad cuando el catálogo
    no trae la ración del alimento."""
    text = _normalize(approx_quantity_text or "")

    explicit = _EXPLICIT_RE.search(text)
    if explicit:
        return round(
            _parse_number(explicit.group(1)) * _UNIT_TO_GRAMS[explicit.group(2).lower()], 1
        )
    spoken = _WORD_QUANTITY_RE.search(text)
    if spoken:
        amount = _NUMBER_WORDS[spoken.group(1).lower()]
        return round(amount * _UNIT_TO_GRAMS[spoken.group(2).lower()], 1)

    group = fg.classify_food(food_name, category) if food_name else None
    size = _size_factor(text)
    for word in re.findall(r"[a-záéíóúñ]+", text):
        measure = _MEASURE_ALIASES.get(word, word)
        if measure in MEASURES:
            return round(_count(text) * measure_grams(measure, group) * size, 1)
        # Porción/ración/trozo: el peso sale del grupo del alimento, no de una tabla fija.
        if _PORTION_ALIASES.get(word, word) in PORTION_MEASURES:
            return round(
                _count(text) * portion_grams(serving_size_g, food_name, category) * size, 1
            )
        # «Dos rebanadas», «un filete»: la unidad natural, la misma que ofrece el desplegable.
        if _UNIT_ALIASES.get(word, word) in UNIT_WORDS:
            return round(
                _count(text) * _unit_grams(serving_size_g, food_name, category) * size, 1
            )

    return round(_count(text) * _unit_grams(serving_size_g, food_name, category) * size, 1)
