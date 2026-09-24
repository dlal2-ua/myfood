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
# «Hoy he almorzado una porción de tortilla» buscaba la frase entera, y Meilisearch exige que
# TODOS los términos aparezcan en el documento: ningún alimento del catálogo contiene
# «almorzado», así que ese fragmento devolvía cero. Se quitan los arranques típicos, y SOLO
# ésos: con un comodín, «pollo que comí ayer» se quedaba en «ayer».
_PREFIX_RES = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        # Cuándo: «hoy», «ayer», «esta mañana»…
        r"^(?:hoy|ayer|anteayer|anoche|esta\s+(?:ma[ñn]ana|tarde|noche)"
        r"|este\s+mediod[ií]a|al\s+mediod[ií]a)\s+",
        # En qué comida: «para cenar», «de desayuno», «en la comida»…
        r"^(?:para\s+(?:desayunar|comer|almorzar|merendar|cenar|picar)"
        r"|de\s+(?:desayuno|comida|almuerzo|merienda|cena)"
        r"|en\s+(?:el\s+desayuno|la\s+comida|el\s+almuerzo|la\s+merienda|la\s+cena))\s+",
        # El verbo: «he comido», «me he tomado», «cené»…
        r"^(?:(?:me\s+)?he\s+(?:comido|tomado|desayunado|almorzado|merendado|cenado|bebido"
        r"|picado|zampado)"
        r"|com[ií]|cen[eé]|desayun[eé]|merend[eé]|tom[eé]|almorc[eé]|almorz[eé])\s+",
    )
]

# «Otra de ensaladilla» → tras quitar «otra» queda «de ensaladilla», que tampoco coincide.
_LEADING_DE_RE = re.compile(r"^de\s+", re.IGNORECASE)
_LEADING_QUANTITY_RE = re.compile(
    r"^(?:\d+(?:[.,]\d+)?|un|una|unos|unas|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez"
    r"|medio|media|otro|otra|otros|otras)\s+",
    re.IGNORECASE,
)
# La medida tampoco se busca: Meilisearch exige que TODOS los términos aparezcan en el
# documento, así que «porción de tortilla de patatas» encuentra menos que «tortilla de
# patatas» — ningún alimento del catálogo se llama «porción de» nada.
_LEADING_MEASURE_RE = re.compile(
    r"^(?:porciones?|porci[oó]n|raci[oó]n|raciones|trozos?|cachos?|pedazos?|rebanadas?|lonchas?"
    r"|filetes?|piezas?|unidades?|platos?|boles?|bol|cuencos?|tazas?|taz[oó]n|tazones|vasos?"
    r"|copas?|cucharadas?|cucharaditas?|pu[ñn]ados?|latas?|cazos?|chorritos?|pizcas?)"
    r"(?:\s+de)?\s+",
    re.IGNORECASE,
)


def split_into_food_mentions(text: str) -> list[str]:
    """Nunca devuelve una lista vacía: si no hay separadores ni cantidad
    reconocible, devuelve el texto original tal cual (mejor buscar la
    frase completa que no buscar nada)."""
    text = text.strip()
    # Varias pasadas: «hoy he almorzado» son dos arranques seguidos.
    for _ in range(3):
        for prefix in _PREFIX_RES:
            text = prefix.sub("", text, count=1).strip()
    fragments = [f.strip() for f in _SEPARATORS_RE.split(text) if f.strip()]
    if not fragments:
        return [text.strip()] if text.strip() else []

    cleaned = []
    for fragment in fragments:
        without_quantity = _LEADING_DE_RE.sub(
            "", _LEADING_QUANTITY_RE.sub("", fragment).strip()
        ).strip()
        # «4 trozos de pan» → «trozos de pan» → «pan»; dos pasadas por si la cantidad va
        # también después de la medida («un par de rebanadas de pan»).
        without_measure = _LEADING_MEASURE_RE.sub("", without_quantity).strip()
        without_measure = _LEADING_QUANTITY_RE.sub("", without_measure).strip()
        without_measure = _LEADING_DE_RE.sub("", without_measure).strip()
        cleaned.append(without_measure or without_quantity or fragment)
    return cleaned
