"""Heurística para convertir la cantidad en texto libre que dio el LLM (`approx_quantity_text`,
sección 10.8 — la IA nunca calcula gramos, R1) en un gramaje por defecto real.

Deliberadamente simple, no es NLP de cantidades: es un punto de partida razonable que el usuario
siempre revisa y corrige antes de confirmar (sección 10.8: «el usuario revisa, ajusta gramos… y
confirma»), nunca el valor final que se guarda sin esa revisión. Reconoce, por este orden:

1. un peso o volumen explícito («200 g», «1 kg», «250 ml», «medio litro»), que se usa tal cual;
2. una medida casera (cucharada, vaso, taza, puñado…) multiplicada por la cantidad;
3. una cantidad de unidades («2», «dos», «media») por el peso de una unidad: la ración del envase
   si el alimento la tiene y, si no, el peso típico de una unidad de su grupo alimentario (un huevo
   pesa ~60 g, una rebanada de pan ~30 g, una pieza de fruta ~130 g…). Antes todo lo desconocido
   pesaba 100 g por unidad y «6 huevos» salía como 600 g.
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

# Medidas caseras (gramos por medida) y su peso cuando el alimento es una grasa de cocina, que
# pesa menos por cucharada que un polvo o un azúcar.
_MEASURES = {
    "cucharadita": 5.0,
    "cucharada": 15.0,
    "chorrito": 5.0,
    "vaso": 200.0,
    "taza": 250.0,
    "tazon": 300.0,
    "copa": 150.0,
    "plato": 250.0,
    "puñado": 30.0,
    "puñados": 30.0,
    "pizca": 1.0,
    "lata": 80.0,
}
_MEASURE_ALIASES = {"cucharadas": "cucharada", "cucharaditas": "cucharadita", "vasos": "vaso",
                    "tazas": "taza", "tazones": "tazon", "copas": "copa", "platos": "plato",
                    "latas": "lata", "tazón": "tazon"}  # fmt: skip
_OIL_MEASURES = {"cucharada": 10.0, "cucharadita": 4.0, "chorrito": 5.0}

# Peso típico de UNA unidad de cada grupo cuando el catálogo no trae la ración.
_UNIT_GRAMS_BY_GROUP = {
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
        if group in _UNIT_GRAMS_BY_GROUP:
            return _UNIT_GRAMS_BY_GROUP[group]
    return DEFAULT_SERVING_GRAMS


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
    for word in re.findall(r"[a-záéíóúñ]+", text):
        measure = _MEASURE_ALIASES.get(word, word)
        if measure in _MEASURES:
            grams = _MEASURES[measure]
            if group == fg.OIL_FAT and measure in _OIL_MEASURES:
                grams = _OIL_MEASURES[measure]
            return round(_count(text) * grams, 1)

    return round(_count(text) * _unit_grams(serving_size_g, food_name, category), 1)
