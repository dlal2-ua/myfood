"""Platos estimados que el usuario ha dado de alta en el catálogo.

Cuando alguien apunta «una marinera», la estimación sale del conocimiento general del modelo
(`ai/prompts.py::MEAL_ESTIMATE_RULES`): el plato entero, con su desglose. Al confirmarla puede
guardar ese plato en `foods`, y desde entonces ya no hace falta volver a pedírselo al modelo:
la próxima «marinera» se resuelve aquí, con los números guardados — menos latencia, cero
tokens y, sobre todo, la misma cifra cada vez.

Estos alimentos NO son dato oficial y no se disfrazan de ello: llevan `source='ai_estimate'`,
que es lo que usa la web para enseñarlos siempre como «aprox.», y quedan fuera del motor de
dietas (`PLAN_SOURCES`), que solo trabaja con fuentes con dato de laboratorio o de etiqueta.

Reconocer un plato guardado en una frase es deliberadamente estricto: o TODO lo que se
menciona son platos guardados y palabras de relleno, o se le pasa la frase al modelo. Un
analizador más listo acabaría apuntando «marinera» cuando se dijo «salsa marinera».
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import Food, FoodComponent, FoodNutrient

ESTIMATE_SOURCE = "ai_estimate"
ESTIMATE_LICENSE = "Estimación orientativa (no es un dato oficial)"
ESTIMATE_ATTRIBUTION = "Estimado por iafood con el conocimiento general del modelo"
# Detrás de todo lo demás (el alta manual de etiqueta es 6): al explorar el catálogo, primero
# lo que tiene dato de verdad.
ESTIMATE_QUALITY_RANK = 7
SERVING_LABEL = "1 ración"

_ARTICLES = {"un", "una", "uno", "unos", "unas", "el", "la", "los", "las"}
_COUNTS: dict[str, float] = {
    "un": 1, "una": 1, "uno": 1, "otro": 1, "otra": 1, "dos": 2, "tres": 3, "cuatro": 4,
    "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
    "medio": 0.5, "media": 0.5,
}  # fmt: skip
# Lo que puede rodear a un plato en una frase sin ser comida: cuándo fue, el verbo, los nexos.
# Cualquier otra palabra que sobre es algo que no se ha entendido, y entonces decide el modelo.
_FILLER = (
    _ARTICLES
    | set(_COUNTS)
    | {
        "y", "e", "con", "mas", "luego", "despues", "tambien", "ademas", "de", "del", "a", "al",
        "en", "para", "por", "que", "hoy", "esta", "este", "manana", "tarde", "noche",
        "mediodia", "me", "he", "tomado", "comido", "bebido", "picado", "desayunado",
        "almorzado", "merendado", "cenado", "tome", "comi", "bebi", "cene", "desayune",
        "merende", "almorce", "desayuno", "desayunar", "comida", "comer", "almuerzo",
        "almorzar", "merienda", "merendar", "cena", "cenar",
    }
)  # fmt: skip

# «Almuerzo» no está: en media España es la comida y en la otra media el bocado de media
# mañana. Sin una pista inequívoca se usa la comida que el usuario tenga elegida.
_MEAL_STEMS: tuple[tuple[str, str], ...] = (
    ("desayun", "breakfast"),
    ("meriend", "afternoon_snack"),
    ("merend", "afternoon_snack"),
    ("cen", "dinner"),
)


def _tokens(text: str) -> list[str]:
    """Palabras en minúscula, sin tildes y en singular «de andar por casa»."""
    plain = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    words = re.findall(r"[a-z0-9]+(?:[.,][0-9]+)?", plain)
    # Solo se quita la «s» final de palabras largas: «marineras» → «marinera», pero «tres» y
    # «seis» se quedan como están. No acierta con «panes», y no pasa nada: ese caso se va al
    # modelo, que es lo que habría pasado sin este módulo.
    return [w[:-1] if len(w) > 4 and w.endswith("s") else w for w in words]


def normalize_name(name: str) -> str:
    """Forma canónica del nombre de un plato, para saber si dos son el mismo."""
    tokens = _tokens(name)
    while tokens and (tokens[0] in _ARTICLES or tokens[0] in _COUNTS):
        tokens = tokens[1:]
    return " ".join(tokens)


@dataclass(frozen=True)
class SavedDish:
    """Un plato estimado ya guardado, con los valores de UNA ración."""

    food_id: str
    name: str
    norm: str
    grams: float
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    components: tuple[dict, ...] = ()
    # Micronutrientes de UNA ración, de las partes que el catálogo confirmó al guardarlo.
    micros: dict | None = None


async def load_saved(session: AsyncSession) -> dict[str, SavedDish]:
    """Todos los platos estimados del catálogo, por nombre canónico.

    Son pocos (los que la gente come de verdad y ha querido guardar), así que se cargan
    enteros en vez de montar una búsqueda aproximada en SQL."""
    rows = (
        await session.execute(
            select(Food, FoodNutrient)
            .join(FoodNutrient, FoodNutrient.food_id == Food.id)
            .where(Food.source == ESTIMATE_SOURCE)
            .order_by(Food.created_at)
        )
    ).all()
    if not rows:
        return {}
    components: dict[uuid.UUID, list[dict]] = {}
    for component in await session.scalars(
        select(FoodComponent)
        .where(FoodComponent.food_id.in_([food.id for food, _ in rows]))
        .order_by(FoodComponent.food_id, FoodComponent.position)
    ):
        components.setdefault(component.food_id, []).append(
            {
                "name": component.name,
                "grams": float(component.grams) if component.grams is not None else None,
                "kcal": float(component.kcal) if component.kcal is not None else None,
            }
        )

    saved: dict[str, SavedDish] = {}
    for food, nutrients in rows:
        norm = normalize_name(food.name_es)
        grams = float(food.serving_size_g or 0)
        if not norm or grams <= 0:
            continue
        factor = grams / 100
        # El primero que se guardó manda: dos altas con el mismo nombre no deberían existir
        # (`save_dish` lo impide), pero si las hubiera no pueden turnarse entre peticiones.
        saved.setdefault(
            norm,
            SavedDish(
                food_id=str(food.id),
                name=food.name_es,
                norm=norm,
                grams=grams,
                kcal=float(nutrients.kcal_100g) * factor,
                protein_g=float(nutrients.protein_100g) * factor,
                fat_g=float(nutrients.fat_100g) * factor,
                carbs_g=float(nutrients.carbs_100g) * factor,
                components=tuple(components.get(food.id, ())),
                micros={
                    key: value * factor
                    for key, value in (nutrients.micros or {}).items()
                    if isinstance(value, int | float)
                },
            ),
        )
    return saved


def _find(tokens: list[str], needle: list[str], start: int = 0) -> int:
    for i in range(start, len(tokens) - len(needle) + 1):
        if tokens[i : i + len(needle)] == needle:
            return i
    return -1


def mentioned(text: str, saved: dict[str, SavedDish]) -> list[SavedDish]:
    """Los platos guardados cuyo nombre aparece tal cual en el texto. Sirve para decírselo al
    modelo: que use ese nombre y no gaste salida en volver a estimarlo."""
    tokens = _tokens(text)
    return [dish for dish in saved.values() if _find(tokens, dish.norm.split()) >= 0]


def detect_meal_type(text: str) -> str | None:
    """La comida que dice el texto, solo cuando lo dice sin ambigüedad."""
    tokens = _tokens(text)
    found: set[str] = set()
    for i, token in enumerate(tokens):
        if token == "media" and tokens[i + 1 : i + 2] == ["manana"]:
            found.add("morning_snack")
        elif token in ("mediodia", "comida", "comer", "comido", "comi"):
            found.add("lunch")
        else:
            for stem, meal_type in _MEAL_STEMS:
                if token.startswith(stem):
                    found.add(meal_type)
    return found.pop() if len(found) == 1 else None


def _count_before(tokens: list[str], index: int) -> float:
    if index == 0:
        return 1.0
    previous = tokens[index - 1]
    if previous in _COUNTS:
        # «a media mañana una marinera»: ese «media» no cuenta marineras.
        return _COUNTS[previous]
    try:
        value = float(previous.replace(",", "."))
    except ValueError:
        return 1.0
    return value if 0 < value <= 20 else 1.0


def resolve_without_model(
    text: str, saved: dict[str, SavedDish]
) -> list[tuple[float, SavedDish]] | None:
    """`[(cuántas, plato)]` si la frase entera son platos guardados; `None` si hay cualquier
    cosa que no se reconoce, y entonces la interpreta el modelo."""
    if not saved:
        return None
    tokens = _tokens(text)
    # Los nombres largos primero: «bocadillo de pastrami con rúcula» antes que «bocadillo».
    by_length = sorted(saved.values(), key=lambda d: len(d.norm.split()), reverse=True)
    out: list[tuple[float, SavedDish]] = []
    i = 0
    while i < len(tokens):
        for dish in by_length:
            needle = dish.norm.split()
            if tokens[i : i + len(needle)] == needle:
                out.append((_count_before(tokens, i), dish))
                i += len(needle)
                break
        else:
            token = tokens[i]
            if token not in _FILLER and not token.replace(",", ".").replace(".", "", 1).isdigit():
                return None
            i += 1
    return out or None


async def save_dish(session: AsyncSession, user_id: UUID, item: dict) -> uuid.UUID:
    """Da de alta en `foods` un plato de una propuesta ya aceptada y devuelve su id.

    `item` es una línea de la propuesta (`domain/diary_proposal.py`), con los totales de lo
    que se comió; aquí se guarda UNA ración. Si ya había un plato con ese nombre se devuelve
    el que había: guardar dos veces no puede dejar dos «marineras» con cifras distintas."""
    name = str(item["name"]).strip()
    existing = (await load_saved(session)).get(normalize_name(name))
    if existing is not None:
        return uuid.UUID(existing.food_id)

    quantity = float(item.get("quantity") or 1) or 1.0
    grams = float(item["grams"]) / quantity
    per_100g = 100 / grams

    food = Food(
        kind="user",
        source=ESTIMATE_SOURCE,
        source_id=None,
        license=ESTIMATE_LICENSE,
        attribution=ESTIMATE_ATTRIBUTION,
        name_es=name,
        serving_size_g=round(grams, 2),
        serving_label=SERVING_LABEL,
        quality_rank=ESTIMATE_QUALITY_RANK,
        created_by=user_id,
    )
    session.add(food)
    await session.flush()
    session.add(
        FoodNutrient(
            food_id=food.id,
            kcal_100g=round(float(item["kcal"]) / quantity * per_100g, 3),
            protein_100g=round(float(item["protein_g"]) / quantity * per_100g, 3),
            fat_100g=round(float(item["fat_g"]) / quantity * per_100g, 3),
            carbs_100g=round(float(item["carbs_g"]) / quantity * per_100g, 3),
            micros={
                key: round(float(value) / quantity * per_100g, 4)
                for key, value in (item.get("micros") or {}).items()
            },
        )
    )
    for position, component in enumerate(item.get("components") or []):
        session.add(
            FoodComponent(
                food_id=food.id,
                position=position,
                name=str(component["name"]),
                # En la propuesta van por el total de lo comido; aquí, por ración.
                grams=_per_unit(component.get("grams"), quantity),
                kcal=_per_unit(component.get("kcal"), quantity),
            )
        )
    await session.flush()
    return food.id


def _per_unit(value: object, quantity: float) -> float | None:
    if value is None:
        return None
    return round(float(value) / quantity, 2)
