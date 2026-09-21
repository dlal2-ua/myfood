"""Sugerencias de alimentos al entrar en «Alimentos»: lo que el usuario ya usa (favoritos,
habituales, recientes), lo que le ayuda hoy (proteína que le falta), básicos para la comida que
toca y lo que tiene en la despensa.

Todo sale de SQL y reglas: la IA no interviene y nunca se calcula un número que no venga de los
datos (R1). Lo que se propone de fuera del historial (proteína, básicos) respeta las alergias,
intolerancias y vetos del usuario. Los alimentos que el usuario eligió él mismo (favoritos,
habituales, recientes, despensa) se muestran tal cual: son suyos.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.domain import food_groups as g
from myfood.domain.food_candidates import EXCLUDE_RESTRICTED_SQL, _group_of, _plausible
from myfood.domain.targets import resolve_targets
from myfood.errors import AppError

SECTION_LIMIT = 10
FREQUENT_DAYS = 60
# Solo se habla de la proteína que falta si es una cantidad que un alimento puede cubrir.
MIN_PROTEIN_GAP_G = 15
_PROTEIN_GROUPS = frozenset({g.MEAT, g.FISH, g.EGG, g.DAIRY, g.CHEESE, g.LEGUME, g.NUTS})
_MIN_PROTEIN_100G = 15
_PER_GROUP = 3

MEAL_STAPLE_GROUPS: dict[str, tuple[str, ...]] = {
    "breakfast": (g.DAIRY, g.CEREAL, g.BREAD, g.FRUIT, g.EGG),
    "morning_snack": (g.FRUIT, g.DAIRY, g.NUTS, g.BREAD),
    "lunch": (g.MEAT, g.FISH, g.EGG, g.LEGUME, g.VEGETABLE, g.GRAIN),
    "afternoon_snack": (g.FRUIT, g.DAIRY, g.NUTS, g.BREAD),
    "dinner": (g.FISH, g.EGG, g.MEAT, g.VEGETABLE, g.DAIRY),
    "supper": (g.DAIRY, g.FRUIT, g.EGG),
}
MEAL_TITLES: dict[str, str] = {
    "breakfast": "Básicos para el desayuno",
    "morning_snack": "Básicos para media mañana",
    "lunch": "Básicos para la comida",
    "afternoon_snack": "Básicos para la merienda",
    "dinner": "Básicos para la cena",
    "supper": "Básicos para la recena",
}

_FOOD_COLUMNS = (
    "f.id, f.name_es, f.brand, f.category, f.source, f.nutriscore_grade, f.nova_group, "
    "f.ecoscore_grade, n.kcal_100g, n.protein_100g, n.fat_100g, n.carbs_100g"
)


@dataclass(frozen=True)
class SuggestedFood:
    id: str
    name_es: str
    brand: str | None
    category: str | None
    source: str
    kcal_100g: float
    protein_100g: float
    fat_100g: float
    carbs_100g: float
    nutriscore_grade: str | None
    nova_group: int | None
    ecoscore_grade: str | None


@dataclass
class SuggestionSection:
    key: str
    title: str
    subtitle: str | None = None
    items: list[SuggestedFood] = field(default_factory=list)


def _food(row) -> SuggestedFood:
    return SuggestedFood(
        id=str(row.id),
        name_es=row.name_es,
        brand=row.brand,
        category=row.category,
        source=row.source,
        kcal_100g=float(row.kcal_100g),
        protein_100g=float(row.protein_100g),
        fat_100g=float(row.fat_100g),
        carbs_100g=float(row.carbs_100g),
        nutriscore_grade=row.nutriscore_grade,
        nova_group=row.nova_group,
        ecoscore_grade=row.ecoscore_grade,
    )


def rotate(items: list, seed: str, key=lambda item: item.id) -> list:
    """Orden estable para un día y un usuario que cambia de un día al siguiente: así los básicos
    no son siempre los mismos, pero no bailan al recargar la pantalla."""
    return sorted(
        items, key=lambda item: hashlib.sha1(f"{seed}:{key(item)}".encode()).hexdigest()
    )


def pick_balanced(
    ordered: list[tuple[str, SuggestedFood]], per_group: int, limit: int
) -> list[SuggestedFood]:
    """Recorre `(grupo, alimento)` en orden y se queda con como mucho `per_group` de cada grupo
    hasta `limit`, para que la lista no sea diez variantes de lo mismo."""
    taken: dict[str, int] = {}
    picked: list[SuggestedFood] = []
    for group, food in ordered:
        if taken.get(group, 0) >= per_group:
            continue
        taken[group] = taken.get(group, 0) + 1
        picked.append(food)
        if len(picked) >= limit:
            break
    return picked


async def _own_foods(session: AsyncSession, sql: str, params: dict) -> list[SuggestedFood]:
    return [_food(row) for row in (await session.execute(text(sql), params)).all()]


async def _official_generics(
    session: AsyncSession, user_id: UUID
) -> list[tuple[str, SuggestedFood]]:
    """Alimentos genéricos de BEDCA (español, dato oficial) permitidos para el usuario, con su
    grupo, coherentes con sus macros y de consumo habitual."""
    rows = (
        await session.execute(
            text(
                f"SELECT {_FOOD_COLUMNS} FROM foods f JOIN food_nutrients n ON n.food_id = f.id "
                f"WHERE f.source = 'bedca' AND n.kcal_100g BETWEEN 20 AND 900 "
                f"AND {EXCLUDE_RESTRICTED_SQL}"
            ),
            {"user_id": str(user_id)},
        )
    ).all()
    generics: list[tuple[str, SuggestedFood]] = []
    for row in rows:
        group = _group_of(row.name_es, row.category)
        food = _food(row)
        if not g.is_staple(group, food.name_es):
            continue
        if not _plausible(group, food.kcal_100g, food.protein_100g, food.fat_100g, food.carbs_100g):
            continue
        generics.append((group, food))
    return generics


async def _protein_gap(session: AsyncSession, user_id: UUID, day: date) -> float | None:
    """Gramos de proteína que faltan hoy para el objetivo, o `None` si no se pueden calcular (perfil
    incompleto) o no falta una cantidad que merezca una sugerencia."""
    try:
        targets = await resolve_targets(session, user_id, action="sugerirte alimentos")
    except AppError:
        return None
    eaten = await session.scalar(
        text(
            "SELECT COALESCE(SUM(protein_g), 0) FROM food_log "
            "WHERE user_id = :u AND log_date = :d"
        ),
        {"u": str(user_id), "d": day},
    )
    gap = targets.protein_g - float(eaten or 0)
    return gap if gap >= MIN_PROTEIN_GAP_G else None


async def build_suggestions(
    session: AsyncSession, user_id: UUID, *, day: date, meal_type: str | None
) -> list[SuggestionSection]:
    uid = {"user_id": str(user_id)}
    sections: list[SuggestionSection] = []
    seen: set[str] = set()

    def add(section: SuggestionSection) -> None:
        section.items = [f for f in section.items if f.id not in seen][:SECTION_LIMIT]
        if section.items:
            seen.update(f.id for f in section.items)
            sections.append(section)

    add(
        SuggestionSection(
            "favorites",
            "Tus favoritos",
            items=await _own_foods(
                session,
                f"SELECT {_FOOD_COLUMNS} FROM user_favorite_foods u "
                "JOIN foods f ON f.id = u.food_id JOIN food_nutrients n ON n.food_id = f.id "
                "WHERE u.user_id = :user_id AND u.food_id IS NOT NULL "
                "ORDER BY u.use_count DESC, u.last_used_at DESC NULLS LAST, f.name_es LIMIT 20",
                uid,
            ),
        )
    )
    add(
        SuggestionSection(
            "frequent",
            "Los que más registras",
            "Los que has apuntado varias veces en los últimos dos meses",
            items=await _own_foods(
                session,
                f"SELECT {_FOOD_COLUMNS} FROM ("
                "  SELECT food_id, COUNT(*) AS uses, MAX(logged_at) AS last_at FROM food_log "
                "  WHERE user_id = :user_id AND food_id IS NOT NULL AND log_date >= :since "
                "  GROUP BY food_id HAVING COUNT(*) >= 2) l "
                "JOIN foods f ON f.id = l.food_id JOIN food_nutrients n ON n.food_id = f.id "
                "ORDER BY l.uses DESC, l.last_at DESC LIMIT 20",
                {**uid, "since": day - timedelta(days=FREQUENT_DAYS)},
            ),
        )
    )
    add(
        SuggestionSection(
            "recent",
            "Registrados hace poco",
            items=await _own_foods(
                session,
                f"SELECT {_FOOD_COLUMNS} FROM ("
                "  SELECT food_id, MAX(logged_at) AS last_at FROM food_log "
                "  WHERE user_id = :user_id AND food_id IS NOT NULL GROUP BY food_id) l "
                "JOIN foods f ON f.id = l.food_id JOIN food_nutrients n ON n.food_id = f.id "
                "ORDER BY l.last_at DESC LIMIT 20",
                uid,
            ),
        )
    )

    add(
        SuggestionSection(
            "pantry",
            "En tu despensa",
            items=await _own_foods(
                session,
                f"SELECT {_FOOD_COLUMNS} FROM pantry_items p "
                "JOIN foods f ON f.id = p.food_id JOIN food_nutrients n ON n.food_id = f.id "
                "WHERE p.user_id = :user_id AND p.quantity_g > 0 "
                "ORDER BY p.expires_on ASC NULLS LAST, f.name_es LIMIT 20",
                uid,
            ),
        )
    )

    generics = await _official_generics(session, user_id)
    seed = f"{user_id}:{day.isoformat()}"

    gap = await _protein_gap(session, user_id, day)
    if gap is not None:
        rich = [
            (group, food)
            for group, food in generics
            if group in _PROTEIN_GROUPS and food.protein_100g >= _MIN_PROTEIN_100G
        ]
        # Primero la proteína «magra»: la que más proteína aporta por caloría (pescado, pavo,
        # pollo, legumbres) antes que frutos secos o quesos curados, con mucha grasa.
        rich.sort(key=lambda gf: -(gf[1].protein_100g * 4 / max(gf[1].kcal_100g, 1)))
        add(
            SuggestionSection(
                "protein",
                f"Hoy te faltan unos {round(gap)} g de proteína",
                "Alimentos ricos en proteína",
                items=pick_balanced(rich, _PER_GROUP, SECTION_LIMIT * 2),
            )
        )

    if meal_type in MEAL_STAPLE_GROUPS:
        wanted = MEAL_STAPLE_GROUPS[meal_type]
        pool = [(group, food) for group, food in generics if group in wanted]
        ordered = rotate(pool, f"{seed}:{meal_type}", key=lambda gf: gf[1].id)
        add(
            SuggestionSection(
                "staples",
                MEAL_TITLES[meal_type],
                items=pick_balanced(ordered, 2, SECTION_LIMIT * 2),
            )
        )

    return sections
