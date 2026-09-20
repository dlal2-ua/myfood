"""Progreso (sección 7.4): `GET /progress/summary` (peso con media móvil de 7 días, adherencia
al registro, kcal medias y tendencia) y `GET /progress/tdee` (histórico del TDEE adaptativo).

Sigue la regla R10: la «adherencia» mide cuántos días registró el usuario, nunca si «cumplió»
su objetivo calórico; el resumen muestra los números sin juzgarlos."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import BodyMeasurement, FoodLog, TdeeEstimate, WaterLog
from myfood.deps import get_current_user_id, get_db
from myfood.domain import progress as progress_calc
from myfood.domain import tdee as tdee_calc
from myfood.domain.targets import resolve_targets
from myfood.errors import AppError

router = APIRouter(prefix="/progress", tags=["progress"])

_PERIODS = {"7d": 7, "30d": 30, "90d": 90, "180d": 180, "365d": 365}


class WeightPoint(BaseModel):
    date: date
    weight_kg: float
    ma7_kg: float


class WeightSummary(BaseModel):
    points: list[WeightPoint]
    start_kg: float | None
    end_kg: float | None
    change_kg: float | None
    trend_kg_per_week: float | None


class DailyIntake(BaseModel):
    date: date
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float


class IntakeSummary(BaseModel):
    logging_days: int
    adherence_pct: float
    avg_kcal: float | None
    avg_protein_g: float | None
    avg_fat_g: float | None
    avg_carbs_g: float | None
    target_kcal: float | None
    daily: list[DailyIntake]


class ProgressSummary(BaseModel):
    period_days: int
    from_date: date
    to_date: date
    weight: WeightSummary
    intake: IntakeSummary
    water_avg_ml: float | None


@router.get("/summary")
async def get_summary(
    period: Annotated[str, Query(pattern=r"^(7|30|90|180|365)d$")] = "30d",
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> ProgressSummary:
    days = _PERIODS[period]
    to_date = date.today()
    from_date = to_date - timedelta(days=days - 1)

    # El peso se suaviza con las pesadas de los 6 días anteriores al periodo también, para que la
    # primera media del periodo no arranque «en frío».
    weight_rows = await session.scalars(
        select(BodyMeasurement)
        .where(
            BodyMeasurement.user_id == user_id,
            BodyMeasurement.measured_on
            >= from_date - timedelta(days=progress_calc.MOVING_AVERAGE_DAYS - 1),
            BodyMeasurement.measured_on <= to_date,
            BodyMeasurement.weight_kg.is_not(None),
        )
        .order_by(BodyMeasurement.measured_on)
    )
    raw = [(m.measured_on, float(m.weight_kg)) for m in weight_rows]
    smoothed = progress_calc.moving_average(raw)
    in_period = [row for row in smoothed if row[0] >= from_date]
    weight = WeightSummary(
        points=[
            WeightPoint(date=d, weight_kg=round(w, 2), ma7_kg=round(ma, 2))
            for d, w, ma in in_period
        ],
        start_kg=round(in_period[0][1], 2) if in_period else None,
        end_kg=round(in_period[-1][1], 2) if in_period else None,
        change_kg=round(in_period[-1][1] - in_period[0][1], 2) if len(in_period) >= 2 else None,
        trend_kg_per_week=(
            round(t, 3)
            if (t := progress_calc.trend_kg_per_week([(d, ma) for d, _, ma in in_period]))
            is not None
            else None
        ),
    )

    food_rows = (
        await session.execute(
            select(
                FoodLog.log_date,
                func.sum(FoodLog.kcal),
                func.sum(FoodLog.protein_g),
                func.sum(FoodLog.fat_g),
                func.sum(FoodLog.carbs_g),
            )
            .where(
                FoodLog.user_id == user_id,
                FoodLog.log_date >= from_date,
                FoodLog.log_date <= to_date,
            )
            .group_by(FoodLog.log_date)
            .order_by(FoodLog.log_date)
        )
    ).all()
    daily = [
        DailyIntake(
            date=d,
            kcal=round(float(k), 1),
            protein_g=round(float(p), 1),
            fat_g=round(float(f), 1),
            carbs_g=round(float(c), 1),
        )
        for d, k, p, f, c in food_rows
    ]
    n = len(daily)
    try:
        target_kcal = round((await resolve_targets(session, user_id)).kcal, 1)
    except AppError:
        target_kcal = None

    intake = IntakeSummary(
        logging_days=n,
        adherence_pct=round(100 * n / days, 1),
        avg_kcal=round(sum(d.kcal for d in daily) / n, 1) if n else None,
        avg_protein_g=round(sum(d.protein_g for d in daily) / n, 1) if n else None,
        avg_fat_g=round(sum(d.fat_g for d in daily) / n, 1) if n else None,
        avg_carbs_g=round(sum(d.carbs_g for d in daily) / n, 1) if n else None,
        target_kcal=target_kcal,
        daily=daily,
    )

    water_rows = (
        await session.execute(
            select(WaterLog.log_date, func.sum(WaterLog.ml))
            .where(
                WaterLog.user_id == user_id,
                WaterLog.log_date >= from_date,
                WaterLog.log_date <= to_date,
            )
            .group_by(WaterLog.log_date)
        )
    ).all()
    water_avg = (
        round(sum(float(ml) for _, ml in water_rows) / len(water_rows), 0) if water_rows else None
    )

    return ProgressSummary(
        period_days=days,
        from_date=from_date,
        to_date=to_date,
        weight=weight,
        intake=intake,
        water_avg_ml=water_avg,
    )


class TdeeEstimateOut(BaseModel):
    week_start: date
    estimated_tdee: float
    avg_intake_kcal: float
    weight_trend_kg: float
    weight_change_kg: float
    logging_days: int
    is_reliable: bool


class TdeeHistory(BaseModel):
    current: TdeeEstimateOut | None
    # `adaptive_tdee` si los objetivos ya parten de esta estimación, `formula` si todavía no es
    # fiable (menos de 14 días de historial o menos de 10 con registro de comidas).
    source: str
    history: list[TdeeEstimateOut]


def _estimate_out(row: TdeeEstimate) -> TdeeEstimateOut:
    return TdeeEstimateOut(
        week_start=row.week_start,
        estimated_tdee=float(row.estimated_tdee),
        avg_intake_kcal=float(row.avg_intake_kcal),
        weight_trend_kg=float(row.weight_trend_kg),
        weight_change_kg=float(row.weight_change_kg),
        logging_days=row.logging_days,
        is_reliable=row.is_reliable,
    )


@router.get("/tdee")
async def get_tdee_history(
    limit: Annotated[int, Query(ge=1, le=104)] = 26,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> TdeeHistory:
    current = await tdee_calc.get_current_estimate(session, user_id)
    rows = await session.scalars(
        select(TdeeEstimate)
        .where(TdeeEstimate.user_id == user_id)
        .order_by(TdeeEstimate.week_start.desc())
        .limit(limit)
    )
    return TdeeHistory(
        current=_estimate_out(current) if current is not None else None,
        source="adaptive_tdee" if current is not None and current.is_reliable else "formula",
        history=[_estimate_out(r) for r in rows],
    )
