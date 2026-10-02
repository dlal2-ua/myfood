"""Afinar con el catálogo lo que el modelo ha estimado.

El modelo estima cada plato entero y lo desglosa en sus partes, con los gramos de cada una
(`ai/prompts.py::MEAL_ESTIMATE_RULES`). Aquí, cada parte se busca entre los alimentos GENÉRICOS
del catálogo —los de tablas de composición: BEDCA, CIQUAL, USDA— y, si hay uno que encaja, sus
valores por 100 g sustituyen a los del modelo: calorías, macros y, sobre todo, los
micronutrientes, que una estimación no trae. Los gramos siguen siendo los del modelo: es lo
que ha visto o lo que se le ha contado.

El orden importa, y es el contrario del que había al principio. Cuando el catálogo era el
punto de partida, «un bocadillo de pastrami» acababa despiezado en lo que el buscador
devolviera, que para «pan» es una quesadilla salvadoreña y para «aceite de oliva» una mayonesa
light. Ahora el plato y sus partes los decide el modelo, y el catálogo solo CONFIRMA: un
alimento del catálogo sustituye a una parte únicamente si se llama igual y sus calorías por
100 g coinciden con las que el modelo esperaba. Si discrepan, lo más probable es que no sea el
mismo alimento (lentejas crudas frente a guisadas, rosquilla dulce frente a rosquilla de pan)
y se queda la estimación. Por construcción, afinar nunca mueve las calorías de una parte más
de `_KCAL_TOLERANCE`.

No se usa Meilisearch: su orden por relevancia es justo el problema. Los genéricos son unos
10.000 nombres; se cargan una vez por proceso y se puntúan todos los que comparten la palabra
principal.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import Food, FoodNutrient
from myfood.domain.estimated_dishes import _tokens

# Fuentes con dato de laboratorio. Los productos de marca (OFF) no entran: «pan» no es el pan
# de molde de una cadena concreta. Tampoco los platos estimados que haya guardado un usuario,
# que se reutilizan por su nombre exacto en `estimated_dishes`.
GENERIC_SOURCES = ("bedca", "ciqual", "usda_foundation", "usda_sr")
# A igualdad de lo demás, la tabla española antes que la francesa, y ésta antes que la
# estadounidense: describen lo que se come aquí.
_SOURCE_BONUS = {"bedca": 0.15, "ciqual": 0.05}

# Cuánto pueden separarse las kcal/100 g del catálogo de las que esperaba el modelo para que
# se consideren el mismo alimento. Con más margen entran los estados equivocados (sepia cruda
# por sepia a la plancha, que pierde agua al cocinarse); con menos, el catálogo no confirma
# casi nada.
_KCAL_TOLERANCE = 0.20
# Para lo que casi no tiene calorías (verduras, café), donde un 20 % son 4 kcal.
_KCAL_ABS_TOLERANCE = 8.0
_EXTRA_TOKEN_PENALTY = 0.08
_MAX_EXTRA_PENALTY = 0.6
_CACHE_SECONDS = 1800

_STOPWORDS = frozenset(
    "de del la el los las con sin a al en y e o un una tipo para por the of".split()
)
# Lo que convierte un alimento en una VARIANTE del normal: si el catálogo lo lleva y lo que
# se comió no lo dice, no es el mismo. Encontrado evaluando contra el catálogo real: sin
# esto, «pan» se confirmaba con «Pan, sin gluten» y «pan tostado» con uno de centeno.
_VARIANT_MARKERS = frozenset(
    "gluten light ligero ligera bajo baja reducido reducida desnatado desnatada "
    "semidesnatado semidesnatada integral centeno enriquecido enriquecida fortificado "
    "fortificada dietetico dietetica edulcorado edulcorada instantaneo instantanea polvo "
    "congelado congelada deshidratado deshidratada seco seca ahumado ahumada almibar "
    "concentrado concentrada infantil vegano vegana relleno rellena conserva enlatado "
    "enlatada germinado germinada".split()
)
_VARIANT_PENALTY = 0.6
# Y lo contrario: palabras que solo dicen que es el de toda la vida. «Pan» es antes el pan
# blanco de barra que el de avena, aunque los dos «empiecen por pan».
_PLAIN_MARKERS = frozenset(
    "blanco blanca comun normal natural entero entera fresco fresca maduro madura barra "
    "trigo gallina vaca medio media".split()
)
_RAW = frozenset({"crudo", "cruda"})
# Lo que se come crudo (un tomate) casi no tiene alternativa en el catálogo y gana igual; para
# lo demás, «jamón» es antes un jamón curado que una pierna de cerdo cruda.
_RAW_PENALTY = 0.15
# Palabras con las que el modelo dice que algo está cocinado. Un alimento crudo del catálogo
# no puede confirmar algo cocinado aunque las calorías se parezcan: la carne pierde agua y
# cambia la proteína por 100 g.
_COOKED = frozenset(
    "plancha frito frita asado asada cocido cocida guisado guisada hervido hervida horno "
    "rebozado rebozada empanado empanada salteado salteada estofado estofada brasa parrilla "
    "tostado tostada".split()
)


def significant_tokens(name: str) -> list[str]:
    """Las palabras que dicen qué alimento es, en el orden en que vienen."""
    return [t for t in _tokens(name) if t not in _STOPWORDS and not t[0].isdigit()]


@dataclass(frozen=True)
class CatalogFood:
    food_id: str
    name: str
    source: str
    tokens: frozenset[str]
    first_token: str
    kcal_100g: float
    protein_100g: float
    fat_100g: float
    carbs_100g: float


class CatalogIndex:
    """Los genéricos del catálogo, indexados por cada palabra de su nombre."""

    def __init__(self, foods: list[CatalogFood]):
        self.by_token: dict[str, list[CatalogFood]] = {}
        for food in foods:
            for token in food.tokens:
                self.by_token.setdefault(token, []).append(food)

    def best_match(self, name: str, kcal_100g: float | None) -> CatalogFood | None:
        """El alimento del catálogo que es «lo mismo» que `name`, o `None`.

        Tres condiciones, y las tres son para no confirmar con un alimento distinto:
        - contiene TODAS las palabras que dicen qué es (las de cómo está cocinado no cuentan):
          «pechuga de pollo a la plancha» no se confirma con una de pavo, y «pan de cristal»
          no se confirma con nada si el catálogo no tiene pan de cristal;
        - su nombre empieza por una de ellas: «aceite de oliva» no es «sardinas en aceite de
          oliva»;
        - sus calorías por 100 g coinciden con las que esperaba el modelo. Sin esa estimación
          con la que contrastar, solo vale que se llame exactamente igual.
        """
        wanted = significant_tokens(name)
        identity = [t for t in wanted if t not in _COOKED]
        if not identity:
            return None
        head, wanted_set, identity_set = identity[0], frozenset(wanted), frozenset(identity)
        is_cooked = bool(wanted_set & _COOKED)
        best: tuple[float, CatalogFood] | None = None
        for food in self.by_token.get(head, ()):
            if not identity_set <= food.tokens or food.first_token not in identity_set:
                continue
            if is_cooked and food.tokens & _RAW:
                continue
            if kcal_100g is None or kcal_100g <= 0:
                if food.tokens != wanted_set:
                    continue
                deviation = 0.0
            else:
                difference = abs(food.kcal_100g - kcal_100g)
                deviation = difference / kcal_100g
                if deviation > _KCAL_TOLERANCE and difference > _KCAL_ABS_TOLERANCE:
                    continue
            extra = food.tokens - wanted_set
            variants = extra & _VARIANT_MARKERS
            plain = extra & _PLAIN_MARKERS
            # Si está cocinado y el catálogo lo tiene cocinado de otra forma, es mejor que
            # crudo, pero peor que el mismo método.
            other_method = (extra & _COOKED) if is_cooked else frozenset()
            ordinary = extra - variants - plain - other_method
            score = (
                (0.3 if food.first_token == head else 0.0)
                + (0.3 if is_cooked and wanted_set & _COOKED & food.tokens else 0.0)
                - min(_MAX_EXTRA_PENALTY, _EXTRA_TOKEN_PENALTY * len(ordinary))
                - _VARIANT_PENALTY * len(variants)
                - (_RAW_PENALTY if extra & _RAW else 0.0)
                + min(0.2, 0.1 * len(plain))
                - 1.5 * min(deviation, 1.0)
                + _SOURCE_BONUS.get(food.source, 0.0)
            )
            if best is None or score > best[0]:
                best = (score, food)
        return best[1] if best else None


_cache: tuple[float, CatalogIndex] | None = None


async def load_index(session: AsyncSession, *, force: bool = False) -> CatalogIndex:
    """El índice, cargado como mucho una vez cada media hora por proceso."""
    global _cache
    now = time.monotonic()
    if not force and _cache is not None and now - _cache[0] < _CACHE_SECONDS:
        return _cache[1]
    rows = (
        await session.execute(
            select(
                Food.id,
                Food.name_es,
                Food.name_short,
                Food.source,
                FoodNutrient.kcal_100g,
                FoodNutrient.protein_100g,
                FoodNutrient.fat_100g,
                FoodNutrient.carbs_100g,
            )
            .join(FoodNutrient, FoodNutrient.food_id == Food.id)
            .where(Food.kind == "generic", Food.source.in_(GENERIC_SOURCES))
        )
    ).all()
    foods = []
    for row in rows:
        # El nombre corto es el que se parece a cómo habla la gente («Lentejas cocidas»); el
        # de la fuente lleva además lo que lo distingue («semillas maduras, hervidas, sin
        # sal»). Se puntúa contra el corto cuando lo hay.
        label = row.name_short or row.name_es
        tokens = significant_tokens(label)
        if not tokens or row.kcal_100g is None:
            continue
        foods.append(
            CatalogFood(
                food_id=str(row.id),
                name=label,
                source=row.source,
                tokens=frozenset(tokens),
                first_token=tokens[0],
                kcal_100g=float(row.kcal_100g),
                protein_100g=float(row.protein_100g or 0),
                fat_100g=float(row.fat_100g or 0),
                carbs_100g=float(row.carbs_100g or 0),
            )
        )
    index = CatalogIndex(foods)
    _cache = (now, index)
    return index


def clear_cache() -> None:
    global _cache
    _cache = None


async def load_micros(session: AsyncSession, food_ids: list[str]) -> dict[str, dict]:
    """Micronutrientes por 100 g de los alimentos elegidos."""
    if not food_ids:
        return {}
    rows = await session.execute(
        select(FoodNutrient.food_id, FoodNutrient.micros).where(
            FoodNutrient.food_id.in_([uuid.UUID(food_id) for food_id in set(food_ids)])
        )
    )
    return {str(food_id): micros or {} for food_id, micros in rows}


def _per_100g(part: dict) -> float | None:
    grams, kcal = part.get("grams"), part.get("kcal")
    if not grams or kcal is None or grams <= 0:
        return None
    return float(kcal) / float(grams) * 100


async def refine_parts(session: AsyncSession, parts: list[dict]) -> dict[str, float]:
    """Confirma con el catálogo cada parte (`{name, grams, kcal, protein_g, fat_g, carbs_g}`).

    Las que encajan pasan a llevar los valores del catálogo para sus gramos y el nombre del
    alimento que las confirma en `catalog`; las demás se quedan como venían. Devuelve los
    micronutrientes que suman las confirmadas, ya escalados a sus gramos.

    Si el catálogo no se puede leer, no se afina nada: una estimación sin afinar sigue siendo
    una respuesta, y un error aquí dejaría al usuario sin ella."""
    try:
        index = await load_index(session)
    except SQLAlchemyError:
        return {}

    matches: list[tuple[dict, CatalogFood]] = []
    for part in parts:
        grams = part.get("grams")
        if not grams or grams <= 0:
            continue
        match = index.best_match(str(part.get("name") or ""), _per_100g(part))
        if match is not None:
            matches.append((part, match))
    if not matches:
        return {}

    try:
        micros_by_food = await load_micros(session, [match.food_id for _, match in matches])
    except SQLAlchemyError:
        micros_by_food = {}

    totals: dict[str, float] = {}
    for part, match in matches:
        factor = float(part["grams"]) / 100
        part["kcal"] = round(match.kcal_100g * factor, 1)
        part["protein_g"] = round(match.protein_100g * factor, 1)
        part["fat_g"] = round(match.fat_100g * factor, 1)
        part["carbs_g"] = round(match.carbs_100g * factor, 1)
        part["catalog"] = match.name
        part["catalog_food_id"] = match.food_id
        for key, value in (micros_by_food.get(match.food_id) or {}).items():
            if isinstance(value, int | float):
                totals[key] = round(totals.get(key, 0.0) + value * factor, 4)
    return totals
