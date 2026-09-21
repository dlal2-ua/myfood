"""Raciones de un alimento: «1 huevo», «1 rebanada», «1 vaso», «100 g».

Nadie pesa un huevo antes de apuntarlo. Hasta ahora el registro solo aceptaba gramos, así que
para anotar dos huevos había que saber que pesan unos 60 g cada uno; las apps de referencia
(Fitia, MyFitnessPal) ofrecen la medida casera y hacen ellas la cuenta.

Los gramos de cada ración los pone el servidor, nunca la pantalla (R1). Se reutilizan las
mismas tablas que ya usa `domain/quantity_text.py` para interpretar el texto libre de Smart
Log: si un huevo pesa 60 g al interpretar «dos huevos», tiene que pesar 60 g también aquí, o
el mismo alimento daría calorías distintas según por dónde se registre.
"""

from __future__ import annotations

from dataclasses import dataclass

from myfood.domain import food_groups as fg
from myfood.domain.quantity_text import (
    MEASURES,
    OIL_MEASURES,
    UNIT_GRAMS_BY_GROUP,
)


@dataclass(frozen=True)
class Portion:
    """`grams` es lo que pesa UNA de estas raciones; la cantidad la pone el usuario."""

    key: str
    label: str
    grams: float


BASE_PORTION = Portion(key="g", label="gramos", grams=1.0)

# Cómo se llama una unidad de cada grupo, en singular. Sin entrada, el grupo no ofrece
# «unidad»: no significa nada decir «una verdura» o «un aceite».
_UNIT_LABELS = {
    fg.EGG: "huevo",
    fg.FRUIT: "pieza",
    fg.BREAD: "rebanada",
    fg.CHEESE: "loncha",
    fg.PROCESSED_MEAT: "loncha",
    fg.MEAT: "filete",
    fg.FISH: "filete",
    fg.VEGETABLE: "pieza",
}

# Medidas caseras que tienen sentido en cada grupo, en orden de uso.
_MEASURES_BY_GROUP: dict[str, tuple[str, ...]] = {
    fg.DAIRY: ("vaso", "taza"),
    fg.BEVERAGE: ("vaso", "taza"),
    fg.OIL_FAT: ("cucharada", "cucharadita", "chorrito"),
    fg.NUTS: ("puñado",),
    fg.CEREAL: ("taza", "puñado"),
    fg.LEGUME: ("plato", "taza"),
    fg.GRAIN: ("plato", "taza"),
    fg.PREPARED: ("plato",),
    fg.SWEET: ("cucharada", "cucharadita"),
}

_MEASURE_LABELS = {
    "vaso": "vaso",
    "taza": "taza",
    "cucharada": "cucharada",
    "cucharadita": "cucharadita",
    "chorrito": "chorrito",
    "puñado": "puñado",
    "plato": "plato",
    "lata": "lata",
}

MAX_PORTIONS = 5


def _measure_grams(measure: str, group: str | None) -> float:
    if group == fg.OIL_FAT and measure in OIL_MEASURES:
        return OIL_MEASURES[measure]
    return MEASURES[measure]


def build_portions(
    *,
    name_es: str | None,
    category: str | None = None,
    serving_size_g: float | None = None,
    serving_label: str | None = None,
) -> list[Portion]:
    """Raciones que se le ofrecen al usuario para este alimento, de la más concreta a la más
    genérica. Los gramos siempre salen de aquí; la pantalla solo multiplica por la cantidad.

    La primera de la lista es la que se propone por defecto: la ración del envase si la hay
    (es la que viene impresa en la etiqueta), luego la unidad natural del alimento, y si no
    hay ninguna, los gramos a secas."""
    portions: list[Portion] = []
    group = fg.classify_food(name_es, category) if name_es else None

    if serving_size_g and serving_size_g > 0:
        label = serving_label.strip() if serving_label and serving_label.strip() else "ración"
        portions.append(Portion(key="serving", label=label, grams=round(float(serving_size_g), 1)))

    unit_label = _UNIT_LABELS.get(group or "")
    if unit_label:
        unit_grams = UNIT_GRAMS_BY_GROUP.get(group or "")
        # Con ración del envase, la unidad ya está cubierta por ella: ofrecer las dos daría
        # dos pesos distintos para la misma cosa.
        if unit_grams and not portions:
            portions.append(Portion(key=f"unit_{group}", label=unit_label, grams=unit_grams))

    for measure in _MEASURES_BY_GROUP.get(group or "", ()):
        portions.append(
            Portion(
                key=measure,
                label=_MEASURE_LABELS.get(measure, measure),
                grams=round(_measure_grams(measure, group), 1),
            )
        )

    portions.append(BASE_PORTION)
    return portions[:MAX_PORTIONS]


def default_grams(portions: list[Portion]) -> float:
    """Cantidad propuesta al abrir el formulario: una ración de la primera opción, o 100 g si
    la única opción son gramos sueltos."""
    first = portions[0] if portions else BASE_PORTION
    return 100.0 if first.key == BASE_PORTION.key else first.grams
