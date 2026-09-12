"""Divide una frase de comida en lenguaje natural en fragmentos que buscar
por separado en Meilisearch (sección 10.8 — RAG de Smart Log).

Encontrado verificando contra el catálogo real (21.801 alimentos): la
configuración de coincidencia por defecto de Meilisearch exige que TODOS
los términos de la consulta aparezcan en el documento para dar un
resultado. Una frase completa como "dos huevos fritos y una tostada con
aceite" no coincide con NINGÚN alimento real (ninguno se llama así), así
que buscarla tal cual devuelve cero resultados — comprobado directamente
contra Meilisearch, no es una suposición. Fragmentos más cortos ("huevos
fritos", "tostada", "aceite") sí encuentran alimentos reales por separado.

La solución: dividir la frase por los conectores más comunes en español
("y", "con", ",", ";") y quitar la palabra de cantidad al principio de
cada fragmento (mismo vocabulario que `quantity_text.py`) antes de
buscarlo. Es una heurística simple, no un analizador sintáctico — puede
partir mal alguna frase (p. ej. separar "tostada" de "con aceite" cuando
en realidad describían un único plato), pero el efecto de sobre-dividir es
inofensivo aquí: cada fragmento de más simplemente aporta más candidatos
al LLM, que solo puede elegir de entre los que existen de verdad (R1).
"""

import re

_SEPARATORS_RE = re.compile(r"\s*(?:,|;|\by\b|\be\b|\bcon\b)\s*", re.IGNORECASE)
_LEADING_QUANTITY_RE = re.compile(
    r"^(?:\d+(?:[.,]\d+)?|un|una|unos|unas|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+",
    re.IGNORECASE,
)


def split_into_food_mentions(text: str) -> list[str]:
    """Nunca devuelve una lista vacía: si no hay separadores ni cantidad
    reconocible, devuelve el texto original tal cual (mejor buscar la
    frase completa que no buscar nada)."""
    fragments = [f.strip() for f in _SEPARATORS_RE.split(text) if f.strip()]
    if not fragments:
        return [text.strip()] if text.strip() else []

    cleaned = []
    for fragment in fragments:
        without_quantity = _LEADING_QUANTITY_RE.sub("", fragment).strip()
        cleaned.append(without_quantity or fragment)
    return cleaned
