"""Planes de dieta generados por el motor determinista (Fase 4, sección
"Motor de generación de dietas"). La IA nunca participa aquí (R1) — este
router solo calcula objetivos con las mismas fórmulas que `/calc/targets`
(R6 ya aplicado ahí) y llama al solver de `domain/diet_engine.py`.

Aislamiento multiusuario (R3 + RLS, sección 22): `diet_plans` tiene RLS
propia (tiene `user_id`). `plan_days`/`plan_meals`/`plan_items`/
`plan_item_alternatives` NO están en la lista de tablas RLS de la migración
0002 (no tienen `user_id` propio) — cualquier acceso a estas pasa primero
por `_get_plan` (RLS + comprobación explícita sobre `diet_plans`) y de ahí
para abajo, igual que el patrón ya usado para `supplement_schedules`.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import (
    BodyMeasurement,
    DietPlan,
    PlanDay,
    PlanItem,
    PlanItemAlternative,
    PlanMeal,
    Profile,
)
from myfood.deps import get_current_user_id, get_db
from myfood.domain import formulas
from myfood.domain.diet_engine import DayTargets, solve_day
from myfood.domain.food_candidates import compute_alternatives_for_item, select_candidates
from myfood.errors import AppError

router = APIRouter(prefix="/diet-plans", tags=["diet-plans"])

_MAX_DAYS = 14

_MEAL_TYPES_BY_COUNT: dict[int, list[str]] = {
    1: ["lunch"],
    2: ["lunch", "dinner"],
    3: ["breakfast", "lunch", "dinner"],
    4: ["breakfast", "lunch", "afternoon_snack", "dinner"],
    5: ["breakfast", "morning_snack", "lunch", "afternoon_snack", "dinner"],
    6: ["breakfast", "morning_snack", "lunch", "afternoon_snack", "dinner", "supper"],
}


def _meal_types_for(meals_per_day: int) -> list[str]:
    clamped = max(1, min(meals_per_day, 6))
    return _MEAL_TYPES_BY_COUNT[clamped]


def _age_years(birth_date: date) -> float:
    return (date.today() - birth_date).days / 365.25


async def _require_complete_profile(session: AsyncSession, user_id: UUID) -> Profile:
    """Mismo requisito que `/calc/targets` (duplicado a propósito — módulos
    independientes, ver el mismo patrón ya usado en `routers/water.py`)."""
    profile = await session.get(Profile, user_id)
    incomplete = (
        profile is None
        or profile.sex is None
        or profile.birth_date is None
        or profile.height_cm is None
    )
    if incomplete:
        raise AppError(
            "PROFILE_INCOMPLETE",
            "Completa sexo, fecha de nacimiento y altura en tu perfil antes de generar un plan.",
            status_code=422,
        )
    return profile


async def _latest_weight_kg(session: AsyncSession, user_id: UUID) -> float | None:
    stmt = (
        select(BodyMeasurement)
        .where(BodyMeasurement.user_id == user_id, BodyMeasurement.weight_kg.is_not(None))
        .order_by(BodyMeasurement.measured_on.desc())
        .limit(1)
    )
    measurement = await session.scalar(stmt)
    return float(measurement.weight_kg) if measurement else None


async def _day_targets(session: AsyncSession, user_id: UUID) -> tuple[Profile, DayTargets]:
    profile = await _require_complete_profile(session, user_id)
    weight_kg = await _latest_weight_kg(session, user_id)
    if weight_kg is None:
        raise AppError(
            "MISSING_MEASUREMENTS",
            "Registra tu peso en Medidas antes de generar un plan.",
            status_code=422,
        )
    height_cm = float(profile.height_cm)
    age_years = _age_years(profile.birth_date)

    bmr = formulas.bmr_mifflin(profile.sex, weight_kg, height_cm, age_years)
    tdee_value = formulas.tdee(bmr, profile.activity_level)
    rate = float(profile.goal_rate_kg_week) if profile.goal_rate_kg_week is not None else 0.5
    kcal, _ = formulas.calorie_target(tdee_value, profile.goal, rate, bmr, profile.sex)
    protein_g, fat_g, carbs_g, _ = formulas.macro_targets(weight_kg, kcal, profile.goal)
    return profile, DayTargets(
        kcal=round(kcal, 1),
        protein_g=round(protein_g, 1),
        fat_g=round(fat_g, 1),
        carbs_g=round(carbs_g, 1),
    )


async def _generate_plan(
    session: AsyncSession, user_id: UUID, name: str, start_date: date, num_days: int
) -> DietPlan:
    _profile, targets = await _day_targets(session, user_id)
    meal_types = _meal_types_for(_profile.meals_per_day)

    candidates = await select_candidates(session, user_id)
    if not candidates:
        raise AppError(
            "NO_CANDIDATE_FOODS",
            "No hay suficientes alimentos disponibles con tus restricciones actuales.",
            status_code=422,
        )

    plan = DietPlan(
        user_id=user_id,
        name=name,
        start_date=start_date,
        end_date=start_date + timedelta(days=num_days - 1),
        status="draft",
        target_kcal=targets.kcal,
        target_protein_g=targets.protein_g,
        target_fat_g=targets.fat_g,
        target_carbs_g=targets.carbs_g,
        generated_by="engine",
    )
    session.add(plan)
    await session.flush()

    recently_used: set[str] = set()
    any_feasible = False
    for day_index in range(num_days):
        day_plan = solve_day(candidates, targets, meal_types, frozenset(recently_used))
        if not day_plan.feasible:
            continue
        any_feasible = True
        plan_day = PlanDay(plan_id=plan.id, day_index=day_index)
        session.add(plan_day)
        await session.flush()
        for sort_order, meal in enumerate(day_plan.meals):
            plan_meal = PlanMeal(
                plan_day_id=plan_day.id, meal_type=meal.meal_type, sort_order=sort_order
            )
            session.add(plan_meal)
            await session.flush()
            for item in meal.items:
                food_uuid = uuid.UUID(item.food_id)
                plan_item = PlanItem(plan_meal_id=plan_meal.id, food_id=food_uuid, grams=item.grams)
                session.add(plan_item)
                await session.flush()
                await compute_alternatives_for_item(
                    session, plan_item.id, food_uuid, item.grams, user_id
                )
                recently_used.add(item.food_id)

    if not any_feasible:
        await session.rollback()
        raise AppError(
            "PLAN_GENERATION_FAILED",
            "No se pudo generar ningún día del plan con los alimentos disponibles.",
            status_code=422,
        )

    await session.commit()
    await session.refresh(plan)
    return plan


async def _get_plan(session: AsyncSession, user_id: UUID, plan_id: UUID) -> DietPlan:
    plan = await session.get(DietPlan, plan_id)
    if plan is None or plan.user_id != user_id:
        raise AppError("PLAN_NOT_FOUND", "No existe ese plan.", status_code=404)
    return plan


class GeneratePlanIn(BaseModel):
    name: str = Field(default="Plan semanal", max_length=200)
    start_date: date | None = None
    num_days: int = Field(default=7, ge=1, le=_MAX_DAYS)


class PlanItemOut(BaseModel):
    id: UUID
    food_id: UUID | None
    name_es: str | None
    grams: float
    is_substitutable: bool
    alternatives: list[PlanItemAlternativeOut]


class PlanItemAlternativeOut(BaseModel):
    id: UUID
    food_id: UUID
    name_es: str
    grams: float
    rank: int
    distance: float


class PlanMealOut(BaseModel):
    id: UUID
    meal_type: str
    items: list[PlanItemOut]


class PlanDayOut(BaseModel):
    id: UUID
    day_index: int
    meals: list[PlanMealOut]
    totals: DayTargets


class DietPlanOut(BaseModel):
    id: UUID
    name: str
    start_date: date
    end_date: date | None
    status: Literal["draft", "active", "archived"]
    target_kcal: float
    target_protein_g: float
    target_fat_g: float
    target_carbs_g: float
    generated_by: str


class DietPlanDetailOut(DietPlanOut):
    days: list[PlanDayOut]


def _plan_to_out(plan: DietPlan) -> DietPlanOut:
    return DietPlanOut(
        id=plan.id,
        name=plan.name,
        start_date=plan.start_date,
        end_date=plan.end_date,
        status=plan.status,
        target_kcal=float(plan.target_kcal),
        target_protein_g=float(plan.target_protein_g),
        target_fat_g=float(plan.target_fat_g),
        target_carbs_g=float(plan.target_carbs_g),
        generated_by=plan.generated_by,
    )


async def _load_plan_detail(session: AsyncSession, plan: DietPlan) -> DietPlanDetailOut:
    rows = (
        await session.execute(
            text("""
                SELECT
                    pd.id AS day_id, pd.day_index,
                    pm.id AS meal_id, pm.meal_type, pm.sort_order,
                    pi.id AS item_id, pi.food_id, f.name_es, pi.grams, pi.is_substitutable,
                    fn.kcal_100g, fn.protein_100g, fn.fat_100g, fn.carbs_100g,
                    pia.id AS alt_id, pia.food_id AS alt_food_id, af.name_es AS alt_name_es,
                    pia.grams AS alt_grams, pia.rank AS alt_rank, pia.distance AS alt_distance
                FROM plan_days pd
                JOIN plan_meals pm ON pm.plan_day_id = pd.id
                JOIN plan_items pi ON pi.plan_meal_id = pm.id
                LEFT JOIN foods f ON f.id = pi.food_id
                LEFT JOIN food_nutrients fn ON fn.food_id = pi.food_id
                LEFT JOIN plan_item_alternatives pia ON pia.plan_item_id = pi.id
                LEFT JOIN foods af ON af.id = pia.food_id
                WHERE pd.plan_id = :plan_id
                ORDER BY pd.day_index, pm.sort_order, pi.id, pia.rank
            """),
            {"plan_id": str(plan.id)},
        )
    ).all()

    days: dict[int, dict] = {}
    for row in rows:
        day = days.setdefault(
            row.day_index,
            {
                "id": row.day_id,
                "meals": {},
                "kcal": 0.0,
                "protein_g": 0.0,
                "fat_g": 0.0,
                "carbs_g": 0.0,
            },
        )
        meal = day["meals"].setdefault(row.meal_id, {"meal_type": row.meal_type, "items": {}})
        is_new_item = row.item_id not in meal["items"]
        item = meal["items"].setdefault(
            row.item_id,
            {
                "id": row.item_id,
                "food_id": row.food_id,
                "name_es": row.name_es,
                "grams": float(row.grams),
                "is_substitutable": row.is_substitutable,
                "alternatives": [],
            },
        )
        # El LEFT JOIN con `plan_item_alternatives` repite una fila por cada
        # alternativa del mismo `plan_item` (hasta 3) — sin `is_new_item` los
        # totales del día se sumarían una vez por alternativa en vez de una
        # vez por alimento (bug real encontrado: daba exactamente 3× el
        # objetivo en cuanto todos los alimentos tenían sus 3 alternativas).
        if is_new_item and row.food_id is not None and row.kcal_100g is not None:
            factor = float(row.grams) / 100
            day["kcal"] += float(row.kcal_100g) * factor
            day["protein_g"] += float(row.protein_100g) * factor
            day["fat_g"] += float(row.fat_100g) * factor
            day["carbs_g"] += float(row.carbs_100g) * factor
        if row.alt_id is not None and not any(a["id"] == row.alt_id for a in item["alternatives"]):
            item["alternatives"].append(
                {
                    "id": row.alt_id,
                    "food_id": row.alt_food_id,
                    "name_es": row.alt_name_es,
                    "grams": float(row.alt_grams),
                    "rank": row.alt_rank,
                    "distance": float(row.alt_distance),
                }
            )

    days_out = [
        PlanDayOut(
            id=day["id"],
            day_index=day_index,
            meals=[
                PlanMealOut(
                    id=meal_id,
                    meal_type=meal["meal_type"],
                    items=[
                        PlanItemOut(
                            id=item["id"],
                            food_id=item["food_id"],
                            name_es=item["name_es"],
                            grams=item["grams"],
                            is_substitutable=item["is_substitutable"],
                            alternatives=[
                                PlanItemAlternativeOut(**alt) for alt in item["alternatives"]
                            ],
                        )
                        for item in meal["items"].values()
                    ],
                )
                for meal_id, meal in day["meals"].items()
            ],
            totals=DayTargets(
                kcal=round(day["kcal"], 1),
                protein_g=round(day["protein_g"], 1),
                fat_g=round(day["fat_g"], 1),
                carbs_g=round(day["carbs_g"], 1),
            ),
        )
        for day_index, day in sorted(days.items())
    ]
    return DietPlanDetailOut(**_plan_to_out(plan).model_dump(), days=days_out)


@router.post("/generate", status_code=201)
async def generate_plan(
    body: GeneratePlanIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> DietPlanDetailOut:
    plan = await _generate_plan(
        session, user_id, body.name, body.start_date or date.today(), body.num_days
    )
    return await _load_plan_detail(session, plan)


@router.get("")
async def list_plans(
    user_id: UUID = Depends(get_current_user_id), session: AsyncSession = Depends(get_db)
) -> list[DietPlanOut]:
    plans = await session.scalars(
        select(DietPlan).where(DietPlan.user_id == user_id).order_by(DietPlan.created_at.desc())
    )
    return [_plan_to_out(p) for p in plans]


@router.get("/{plan_id}")
async def get_plan(
    plan_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> DietPlanDetailOut:
    plan = await _get_plan(session, user_id, plan_id)
    return await _load_plan_detail(session, plan)


class PlanStatusPatch(BaseModel):
    status: Literal["draft", "active", "archived"]


@router.patch("/{plan_id}")
async def update_plan_status(
    plan_id: UUID,
    body: PlanStatusPatch,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> DietPlanOut:
    plan = await _get_plan(session, user_id, plan_id)
    plan.status = body.status
    await session.commit()
    await session.refresh(plan)
    return _plan_to_out(plan)


@router.delete("/{plan_id}", status_code=204)
async def delete_plan(
    plan_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> None:
    plan = await _get_plan(session, user_id, plan_id)
    await session.delete(plan)
    await session.commit()


class SubstituteIn(BaseModel):
    alternative_id: UUID


@router.post("/{plan_id}/items/{item_id}/substitute")
async def substitute_item(
    plan_id: UUID,
    item_id: UUID,
    body: SubstituteIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> PlanItemOut:
    await _get_plan(session, user_id, plan_id)  # confirma propiedad del plan (RLS + check)

    row = (
        await session.execute(
            text("""
                SELECT pi.id, pi.plan_meal_id, pi.is_substitutable
                FROM plan_items pi
                JOIN plan_meals pm ON pm.id = pi.plan_meal_id
                JOIN plan_days pd ON pd.id = pm.plan_day_id
                WHERE pi.id = :item_id AND pd.plan_id = :plan_id
            """),
            {"item_id": str(item_id), "plan_id": str(plan_id)},
        )
    ).first()
    if row is None:
        raise AppError("PLAN_ITEM_NOT_FOUND", "No existe ese elemento del plan.", status_code=404)
    if not row.is_substitutable:
        raise AppError(
            "ITEM_NOT_SUBSTITUTABLE", "Este elemento no admite sustitución.", status_code=422
        )

    item = await session.get(PlanItem, item_id)
    alternative = await session.get(PlanItemAlternative, body.alternative_id)
    if alternative is None or alternative.plan_item_id != item_id:
        raise AppError(
            "ALTERNATIVE_NOT_FOUND",
            "Esa alternativa no pertenece a este elemento.",
            status_code=404,
        )

    item.food_id = alternative.food_id
    item.grams = alternative.grams
    await session.execute(
        delete(PlanItemAlternative).where(PlanItemAlternative.plan_item_id == item_id)
    )
    await session.flush()
    await compute_alternatives_for_item(session, item.id, item.food_id, float(item.grams), user_id)
    await session.commit()

    rows = (
        await session.execute(
            text("""
                SELECT f.name_es AS item_name_es,
                       pia.id AS alt_id, pia.food_id AS alt_food_id, af.name_es AS alt_name_es,
                       pia.grams AS alt_grams, pia.rank AS alt_rank, pia.distance AS alt_distance
                FROM foods f
                LEFT JOIN plan_item_alternatives pia ON pia.plan_item_id = :item_id
                LEFT JOIN foods af ON af.id = pia.food_id
                WHERE f.id = :food_id
                ORDER BY pia.rank
            """),
            {"item_id": str(item_id), "food_id": str(item.food_id)},
        )
    ).all()
    name_es = rows[0].item_name_es if rows else None
    alternatives = [
        PlanItemAlternativeOut(
            id=r.alt_id,
            food_id=r.alt_food_id,
            name_es=r.alt_name_es,
            grams=float(r.alt_grams),
            rank=r.alt_rank,
            distance=float(r.alt_distance),
        )
        for r in rows
        if r.alt_id is not None
    ]
    return PlanItemOut(
        id=item.id,
        food_id=item.food_id,
        name_es=name_es,
        grams=float(item.grams),
        is_substitutable=item.is_substitutable,
        alternatives=alternatives,
    )
