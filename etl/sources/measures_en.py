"""Cantidades en inglés («3/4 cup», «1 1/2 tbsp», «2 oz») a gramos.

TheMealDB da las cantidades como las escribiría una persona, en medidas caseras inglesas.
MyFood ya sabe pasar medidas caseras a gramos (`domain/quantity_text`), pero en español, así
que aquí solo se traduce la MEDIDA al término español equivalente y se delega: una taza pesa
lo mismo venga de donde venga, y no queremos dos tablas que puedan desajustarse.

Las fracciones son lo específico de esta fuente: «1 1/2» y «3/4» no aparecen en el texto libre
que escribe un usuario español, y `quantity_text` no las entiende.
"""

from __future__ import annotations

import re

# Medida inglesa -> el término español que ya conoce `quantity_text`.
MEASURE_WORDS = {
    "cup": "taza",
    "cups": "taza",
    "tbsp": "cucharada",
    "tbs": "cucharada",
    "tblsp": "cucharada",
    "tablespoon": "cucharada",
    "tablespoons": "cucharada",
    "tsp": "cucharadita",
    "teaspoon": "cucharadita",
    "teaspoons": "cucharadita",
    "pinch": "pizca",
    "pinches": "pizca",
    "handful": "puñado",
    "handfuls": "puñado",
    "glass": "vaso",
    "glasses": "vaso",
    "can": "lata",
    "cans": "lata",
    "tin": "lata",
    "bowl": "tazon",
    "dash": "pizca",
    "splash": "chorrito",
    "drizzle": "chorrito",
}

# Unidades de peso y volumen: se convierten aquí, sin pasar por medidas caseras.
UNIT_GRAMS = {
    "g": 1.0, "gr": 1.0, "gram": 1.0, "grams": 1.0, "gm": 1.0,
    "kg": 1000.0, "kilo": 1000.0, "kilos": 1000.0,
    "ml": 1.0, "milliliter": 1.0, "millilitre": 1.0, "cl": 10.0,
    "l": 1000.0, "litre": 1000.0, "liter": 1000.0, "litres": 1000.0, "liters": 1000.0,
    "oz": 28.35, "ounce": 28.35, "ounces": 28.35,
    "lb": 453.6, "lbs": 453.6, "pound": 453.6, "pounds": 453.6,
}  # fmt: skip

# Cosas que se cuentan por piezas y cuyo peso típico no está en el catálogo.
PIECE_GRAMS = {
    "clove": 5.0, "cloves": 5.0,        # ajo
    "sprig": 2.0, "sprigs": 2.0,        # hierbas
    "leaf": 1.0, "leaves": 1.0,
    "slice": 25.0, "slices": 25.0,
    "stick": 100.0, "sticks": 100.0,
    "rasher": 25.0, "rashers": 25.0,    # bacon
    "fillet": 150.0, "fillets": 150.0,
}

_FRACTIONS = {
    "½": 0.5, "⅓": 1 / 3, "⅔": 2 / 3, "¼": 0.25, "¾": 0.75,
    "⅕": 0.2, "⅙": 1 / 6, "⅛": 0.125, "⅜": 0.375, "⅝": 0.625, "⅞": 0.875,
}  # fmt: skip

_NUMBER_RE = re.compile(r"(\d+)\s*/\s*(\d+)|(\d+(?:[.,]\d+)?)")


def parse_amount(text: str) -> float | None:
    """La cantidad de «3/4», «1 1/2», «2.5» o «½». `None` si no hay número.

    Un entero seguido de una fracción se suma («1 1/2» son 1,5), que es como se escriben las
    recetas en inglés; en cualquier otro caso manda el primer número."""
    cleaned = text.strip().lower()
    for symbol, value in _FRACTIONS.items():
        if symbol in cleaned:
            whole = re.match(r"\s*(\d+)", cleaned)
            return (float(whole.group(1)) if whole else 0.0) + value

    matches = _NUMBER_RE.findall(cleaned)
    if not matches:
        return None

    values: list[float] = []
    for numerator, denominator, plain in matches:
        if numerator and denominator:
            # Un denominador cero es un error de escritura en la receta: vale más quedarse
            # con el numerador que descartar la cantidad entera.
            values.append(
                float(numerator) / float(denominator) if float(denominator) else float(numerator)
            )
        elif plain:
            values.append(float(plain.replace(",", ".")))
    if not values:
        return None
    # «1 1/2»: entero + fracción. Solo se suman si el primero es entero y el segundo, menor que 1.
    if len(values) >= 2 and values[0].is_integer() and 0 < values[1] < 1:
        return values[0] + values[1]
    return values[0]


def to_spanish_quantity(measure: str) -> str:
    """La cantidad tal cual, con la medida traducida al término que entiende `quantity_text`.

    Lo que sale de aquí es texto para `resolve_grams`, no un número: quien decide cuánto pesa
    una taza o una cucharada sigue siendo la tabla del dominio, no esta capa."""
    text = (measure or "").strip().lower()
    if not text:
        return ""
    amount = parse_amount(text)
    words = re.findall(r"[a-zá-ú]+", text)

    for word in words:
        if word in UNIT_GRAMS:
            grams = (amount or 1.0) * UNIT_GRAMS[word]
            return f"{grams:g} g"
        if word in PIECE_GRAMS:
            grams = (amount or 1.0) * PIECE_GRAMS[word]
            return f"{grams:g} g"
        if word in MEASURE_WORDS:
            return f"{amount or 1:g} {MEASURE_WORDS[word]}"

    # Sin medida reconocida: es un recuento de piezas («2 onions», «1 lemon»), y cuánto pesa
    # una pieza lo sabe `quantity_text` por el grupo del alimento.
    return f"{amount:g}" if amount is not None else ""
