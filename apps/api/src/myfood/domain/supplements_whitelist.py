"""Lista blanca cerrada de suplementos que iafood puede sugerir (sección 10.7).

La IA solo elige una CLAVE de esta lista; nunca propone una dosis. Cada entrada lleva su dosis
habitual y su límite superior (UL) definidos aquí, en código: el backend es quien rellena la dosis.
Las sugerencias que se apoyan en datos de ingesta (`micro_key`) solo se aceptan si la ingesta media
del usuario queda por debajo de la referencia — nunca se sugiere magnesio a quien ya llega al 100 %.

Los valores son orientativos (EFSA) y se muestran siempre con el aviso de que no sustituyen el
consejo de un profesional sanitario (R7).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WhitelistedSupplement:
    key: str
    name_es: str
    type: str
    dose_amount: float
    dose_unit: str
    # Rango habitual de una toma y límite superior diario; la dosis sugerida nunca lo supera.
    dose_min: float
    dose_max: float
    upper_limit: float | None
    # Micronutriente del catálogo (`domain/micronutrients.py`) que cubre, si lo hay. Con él, la
    # sugerencia exige una ingesta media por debajo de `MICRO_SUGGEST_BELOW_PCT` de la referencia.
    micro_key: str | None = None
    # Palabras del nombre o tipo de un suplemento que indican que el usuario ya lo toma.
    aliases: tuple[str, ...] = ()


MICRO_SUGGEST_BELOW_PCT = 80.0

WHITELIST: tuple[WhitelistedSupplement, ...] = (
    WhitelistedSupplement(
        "protein", "Proteína en polvo", "protein", 25, "g", 20, 40, 60,
        aliases=("proteina", "protein", "whey"),
    ),
    WhitelistedSupplement(
        "creatine", "Creatina monohidrato", "creatine", 5, "g", 3, 5, 5,
        aliases=("creatina", "creatine"),
    ),
    WhitelistedSupplement(
        "magnesium", "Magnesio", "magnesium", 200, "mg", 100, 250, 250,
        micro_key="magnesium_mg", aliases=("magnesio", "magnesium"),
    ),
    WhitelistedSupplement(
        "omega3", "Omega-3 (EPA+DHA)", "omega3", 500, "mg", 250, 1000, 3000,
        aliases=("omega", "epa", "dha", "aceite de pescado", "fish oil"),
    ),
    WhitelistedSupplement(
        "vitamin_d", "Vitamina D", "vitamin_d", 15, "µg", 10, 25, 100,
        micro_key="vitamin_d_ug", aliases=("vitamina d", "vitamin d", "colecalciferol"),
    ),
    WhitelistedSupplement(
        "vitamin_b12", "Vitamina B12", "vitamin_b12", 10, "µg", 2.5, 25, 100,
        micro_key="vitamin_b12_ug", aliases=("b12", "cobalamina", "cianocobalamina"),
    ),
    WhitelistedSupplement(
        "iron", "Hierro", "iron", 14, "mg", 8, 18, 40,
        micro_key="iron_mg", aliases=("hierro", "iron"),
    ),
    WhitelistedSupplement(
        "zinc", "Zinc", "zinc", 10, "mg", 5, 15, 25,
        micro_key="zinc_mg", aliases=("zinc",),
    ),
    WhitelistedSupplement(
        "calcium", "Calcio", "calcium", 500, "mg", 250, 600, 2500,
        micro_key="calcium_mg", aliases=("calcio", "calcium"),
    ),
    WhitelistedSupplement(
        "multivitamin", "Multivitamínico", "multivitamin", 1, "cápsula", 1, 1, 1,
        aliases=("multivit", "multivitam"),
    ),
)  # fmt: skip

BY_KEY: dict[str, WhitelistedSupplement] = {s.key: s for s in WHITELIST}
KEYS: tuple[str, ...] = tuple(BY_KEY)

DISCLAIMER = (
    "Esto no es consejo médico ni una prescripción: son ideas orientativas a partir de tu "
    "alimentación registrada. Consulta con un médico o un dietista-nutricionista antes de tomar "
    "cualquier suplemento, sobre todo si tomas medicación."
)


def suggested_dose(entry: WhitelistedSupplement) -> float:
    """Dosis que rellena el backend: la habitual, sin pasar nunca del máximo ni del UL."""
    ceiling = min(entry.dose_max, entry.upper_limit) if entry.upper_limit else entry.dose_max
    return min(max(entry.dose_amount, entry.dose_min), ceiling)


def already_taking(entry: WhitelistedSupplement, supplements: list[tuple[str, str]]) -> bool:
    """¿Alguno de los suplementos `(nombre, tipo)` del usuario es este?"""
    for name, type_ in supplements:
        haystack = f"{name} {type_}".lower()
        if type_ == entry.type or any(alias in haystack for alias in entry.aliases):
            return True
    return False
