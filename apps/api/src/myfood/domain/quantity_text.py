"""Heurística mínima para convertir la cantidad en texto libre que dio el
LLM (`approx_quantity_text`, sección 10.8 — la IA nunca calcula gramos, R1)
en un gramaje por defecto real. Deliberadamente simple: reconoce números en
dígitos, gramos explícitos ("200 g", "200 gramos") y las palabras españolas
para 1-10 — cualquier otra cosa ("un puñado", "una ración generosa") cae al
valor por defecto de 1 unidad. No es NLP de cantidades — es un punto de
partida razonable que el usuario siempre revisa y puede corregir antes de
confirmar (sección 10.8: "el usuario revisa, ajusta gramos... y confirma"),
nunca el valor final que se guarda sin pasar por esa revisión.
"""

from __future__ import annotations

import re

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
}

# "200 g" / "200g" / "200 gramos" / "200gr" — un peso explícito en gramos,
# se usa TAL CUAL en vez de multiplicar por la ración del alimento.
_EXPLICIT_GRAMS_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:g|gr|gramo|gramos)\b", re.IGNORECASE
)
_DIGIT_QUANTITY_RE = re.compile(r"(\d+(?:[.,]\d+)?)")


def resolve_grams(approx_quantity_text: str, serving_size_g: float | None) -> float:
    """Devuelve el gramaje por defecto para un item de Smart Log. Un peso
    explícito en gramos en el propio texto gana siempre; si no, se
    multiplica la ración habitual del alimento (o `DEFAULT_SERVING_GRAMS`
    si el catálogo no la tiene) por la cantidad detectada (por defecto 1)."""
    text = (approx_quantity_text or "").strip().lower()

    explicit = _EXPLICIT_GRAMS_RE.search(text)
    if explicit:
        return round(float(explicit.group(1).replace(",", ".")), 1)

    base = float(serving_size_g) if serving_size_g else DEFAULT_SERVING_GRAMS
    multiplier = _quantity_multiplier(text)
    return round(base * multiplier, 1)


def _quantity_multiplier(text: str) -> float:
    digit_match = _DIGIT_QUANTITY_RE.search(text)
    if digit_match:
        return float(digit_match.group(1).replace(",", "."))
    for word, value in _NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", text):
            return float(value)
    return 1.0
