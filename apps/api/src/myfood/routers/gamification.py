"""Gamificación ética (Fase 7, R10) — GET /gamification/summary: racha de
registro, heatmap de actividad y logros. Ver `domain/gamification.py` para
las reglas derivadas de R10 (nunca colorea/premia por resultado calórico o
corporal, solo por constancia de uso)."""

from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import FoodLog, Recipe, WaterLog
from myfood.deps import get_current_user_id, get_db
from myfood.domain.gamification import build_achievements, compute_streaks

router = APIRouter(prefix="/gamification", tags=["gamification"])

_HEATMAP_DAYS = 365


class HeatmapDay(BaseModel):
    date: str
    count: int


class AchievementOut(BaseModel):
    key: str
    title: str
    description: str
    earned: bool
    progress: int
    target: int


class GamificationSummary(BaseModel):
    current_streak: int
    longest_streak: int
    heatmap: list[HeatmapDay]
    achievements: list[AchievementOut]


@router.get("/summary")
async def get_summary(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> GamificationSummary:
    today = date.today()

    all_food_dates = set(
        await session.scalars(
            select(FoodLog.log_date).where(FoodLog.user_id == user_id).distinct()
        )
    )
    current_streak, longest_streak = compute_streaks(all_food_dates, today=today)

    water_logging_days = await session.scalar(
        select(func.count(func.distinct(WaterLog.log_date))).where(WaterLog.user_id == user_id)
    )
    distinct_recipes = await session.scalar(
        select(func.count()).select_from(Recipe).where(Recipe.user_id == user_id)
    )
    achievements = build_achievements(
        longest_streak=longest_streak,
        water_logging_days=water_logging_days or 0,
        distinct_recipes=distinct_recipes or 0,
    )

    window_start = today - timedelta(days=_HEATMAP_DAYS - 1)
    counts_by_day: dict[date, int] = dict(
        (
            await session.execute(
                select(FoodLog.log_date, func.count())
                .where(FoodLog.user_id == user_id, FoodLog.log_date >= window_start)
                .group_by(FoodLog.log_date)
            )
        ).all()
    )
    heatmap = [
        HeatmapDay(
            date=(window_start + timedelta(days=offset)).isoformat(),
            count=counts_by_day.get(window_start + timedelta(days=offset), 0),
        )
        for offset in range(_HEATMAP_DAYS)
    ]

    return GamificationSummary(
        current_streak=current_streak,
        longest_streak=longest_streak,
        heatmap=heatmap,
        achievements=[AchievementOut(**a.__dict__) for a in achievements],
    )
