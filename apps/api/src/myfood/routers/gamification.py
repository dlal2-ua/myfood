"""Gamificación ética (Fase 7, R10) — GET /gamification/summary: racha de
registro, heatmap de actividad y logros con su insignia. Ver
`domain/gamification.py` para las reglas derivadas de R10 (nunca colorea ni
premia por resultado calórico o corporal, solo por constancia de uso).

Los logros conseguidos se guardan en `user_achievements` la primera vez que
se detectan, para poder decir CUÁNDO se consiguieron y avisar una sola vez
(el aviso lo manda el worker, regla 19)."""

from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import FoodLog
from myfood.deps import get_current_user_id, get_db
from myfood.domain.achievements import collect_counters, sync_achievements
from myfood.domain.gamification import build_achievements

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
    icon: str
    tier: str
    family: str
    earned_on: str | None = None


class GamificationSummary(BaseModel):
    current_streak: int
    longest_streak: int
    heatmap: list[HeatmapDay]
    achievements: list[AchievementOut]
    # Conseguidos justo en esta llamada: la pantalla los celebra una vez.
    newly_earned: list[str]


@router.get("/summary")
async def get_summary(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> GamificationSummary:
    today = date.today()
    counters, current_streak, longest_streak = await collect_counters(
        session, user_id, today=today
    )
    achievements = build_achievements(**counters)
    earned_on, newly_earned = await sync_achievements(
        session, user_id, achievements, today=today
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
        achievements=[
            AchievementOut(
                **a.__dict__,
                earned_on=earned_on[a.key].isoformat() if a.key in earned_on else None,
            )
            for a in achievements
        ],
        newly_earned=newly_earned,
    )
