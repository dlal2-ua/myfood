"""Raciones de un alimento: «1 huevo», «1 rebanada», «1 vaso», «100 g».

Nadie pesa un huevo antes de apuntarlo. Hasta ahora el registro solo aceptaba gramos, así que
para anotar dos huevos había que saber que pesan unos 60 g cada uno; las apps de referencia
(Fitia, MyFitnessPal) ofrecen la medida casera y hacen ellas la cuenta.

Los gramos de cada ración los pone el servidor, nunca la pantalla (R1). Se reutilizan las
mismas tablas que ya usa `domain/quantity_text.py` para interpretar el texto libre de Smart
Log: si un huevo pesa 60 g al interpretar «dos huevos», tiene que pesar 60 g también aquí, o
el mismo alimento daría calorías distintas según por dónde se registre. Por eso el peso de una
medida se pide a `quantity_text.measure_grams` en vez de mirar `MEASURES` directamente: ahí es
donde vive la corrección por densidad (una taza de cereales no pesa lo que una taza de guiso).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from myfood.domain import food_groups as fg
from myfood.domain.quantity_text import (
    UNIT_GRAMS_BY_GROUP,
    measure_grams,
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


# La etiqueta de ración de Open Food Facts suele ser el propio peso («100g», «30 g», «250ml»),
# que ya se enseña al lado: repetirla daba «100g (100 g)».
_WEIGHT_LABEL_RE = re.compile(
    r"^\s*\d+(?:[.,]\d+)?\s*(?:g|gr|gramos?|ml|mililitros?|cl|l)\s*$", re.IGNORECASE
)


def _serving_label(raw: str | None) -> str | None:
    """Etiqueta que merece la pena enseñar, o `None` si solo repite el gramaje."""
    label = (raw or "").strip()
    if not label or _WEIGHT_LABEL_RE.match(label):
        return None
    return label


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
        grams = round(float(serving_size_g), 1)
        label = _serving_label(serving_label)
        # Una «ración» de 100 g no añade nada sobre los gramos sueltos, y con la etiqueta de
        # Open Food Facts (que suele ser el propio peso) quedaba «100g (100 g)».
        if not (label is None and grams == 100):
            portions.append(Portion(key="serving", label=label or "ración", grams=grams))

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
                grams=round(measure_grams(measure, group), 1),
            )
        )

    portions.append(BASE_PORTION)
    return portions[:MAX_PORTIONS]


def default_grams(portions: list[Portion]) -> float:
    """Cantidad propuesta al abrir el formulario: una ración de la primera opción, o 100 g si
    la única opción son gramos sueltos."""
    first = portions[0] if portions else BASE_PORTION
    return 100.0 if first.key == BASE_PORTION.key else first.grams
