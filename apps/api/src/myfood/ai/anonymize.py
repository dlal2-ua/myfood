"""Anonimización para iafood (R5/sección 10.2) — único punto por el que
sale información hacia el LLM. Ningún otro módulo debe montar a mano el
payload que se le pasa al Claude Agent SDK.

Lo que SÍ sale: objetivos numéricos ya calculados, banda de edad (nunca la
fecha de nacimiento), nombres de alimentos (dato de catálogo, no personal).
Lo que NUNCA sale: nombre, email, `user_id`, fecha de nacimiento exacta,
peso/altura exactos, la cifra exacta de presupuesto. Los `food_id` reales
(UUID) se sustituyen por alias efímeros (`c1`, `c2`, ...) que solo existen
en memoria durante la sesión — el mapeo inverso nunca sale del servidor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import Allergen, Food, Profile, UserRestriction
from myfood.domain.diet_engine import CandidateFood, DayTargets

_AGE_BANDS = (
    (18, 25, "18-24"),
    (25, 35, "25-34"),
    (35, 45, "35-44"),
    (45, 55, "45-54"),
    (55, 65, "55-64"),
)


def age_band(birth_date: date) -> str:
    age_years = (date.today() - birth_date).days / 365.25
    if age_years < 18:
        return "<18"
    for lower, upper, label in _AGE_BANDS:
        if lower <= age_years < upper:
            return label
    return "65+"


def budget_band(budget_eur_week: float | None) -> str | None:
    """Umbrales orientativos, no fijados por la especificación: un
    presupuesto semanal de comida por persona en España ronda 30-60€ para
    uso moderado — referencia aproximada para bandear la cifra, no un
    valor verificado externamente ni algo que deba tratarse como preciso."""
    if budget_eur_week is None:
        return None
    if budget_eur_week < 40:
        return "low"
    if budget_eur_week <= 80:
        return "medium"
    return "high"


@dataclass
class AnonymizedPayload:
    payload: dict
    alias_to_food_id: dict[str, str]


def _candidates_out(candidates: list[CandidateFood]) -> tuple[list[dict], dict[str, str]]:
    alias_to_food_id: dict[str, str] = {}
    out = []
    for index, food in enumerate(candidates, start=1):
        alias = f"c{index}"
        alias_to_food_id[alias] = food.id
        out.append(
            {
                "id": alias,
                "name": food.name_es,
                "category": food.category,
                "kcal_100g": food.kcal_100g,
                "protein_100g": food.protein_100g,
                "fat_100g": food.fat_100g,
                "carbs_100g": food.carbs_100g,
            }
        )
    return out, alias_to_food_id


async def _restrictions_out(session: AsyncSession, user_id: UUID) -> dict[str, list[str]]:
    rows = (
        await session.execute(
            select(UserRestriction, Allergen.name_es, Food.name_es)
            .outerjoin(Allergen, Allergen.code == UserRestriction.allergen_code)
            .outerjoin(Food, Food.id == UserRestriction.food_id)
            .where(UserRestriction.user_id == user_id)
        )
    ).all()
    allergens = sorted(
        {
            restriction.allergen_code
            for restriction, _allergen_name, _food_name in rows
            if restriction.kind in ("allergen", "intolerance") and restriction.allergen_code
        }
    )
    disliked = sorted(
        {
            food_name
            for restriction, _allergen_name, food_name in rows
            if restriction.kind in ("disliked_food", "banned_food", "intolerance")
            and food_name is not None
        }
    )
    return {"allergens": allergens, "disliked": disliked}


async def build_diet_plan_payload(
    session: AsyncSession,
    *,
    profile: Profile,
    targets: DayTargets,
    meals_per_day: int,
    candidates: list[CandidateFood],
) -> AnonymizedPayload:
    candidates_out, alias_to_food_id = _candidates_out(candidates)
    restrictions = await _restrictions_out(session, profile.user_id)

    payload = {
        "targets": {
            "kcal": targets.kcal,
            "protein_g": targets.protein_g,
            "fat_g": targets.fat_g,
            "carbs_g": targets.carbs_g,
        },
        "context": {
            "sex": profile.sex,
            "age_band": age_band(profile.birth_date),
            "activity_level": profile.activity_level,
            "goal": profile.goal,
            "meals_per_day": meals_per_day,
            "diet_style": profile.diet_style,
            "max_cook_minutes": profile.max_cook_minutes,
            "budget_band": budget_band(
                float(profile.budget_eur_week) if profile.budget_eur_week is not None else None
            ),
        },
        "restrictions": restrictions,
        "candidates": candidates_out,
    }
    return AnonymizedPayload(payload=payload, alias_to_food_id=alias_to_food_id)
