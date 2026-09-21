"""Contadores de los logros y su persistencia (Fase 7, R10).

Las reglas de qué es cada logro viven en `domain/gamification.py` y son puras. Aquí está
lo único que necesita la base de datos: contar lo que lleva hecho el usuario y recordar
qué logros ya tiene, para poder decir cuándo los consiguió y avisar una sola vez.

Módulo aparte del router porque lo usan dos sitios muy distintos: `routers/gamification.py`
(al abrir «Progreso», con la sesión del usuario) y el `worker` (barrido periódico con
sesión de administración, que es quien manda el aviso — regla 19).
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import FoodLog, Recipe, UserAchievement, WaterLog
from myfood.domain.gamification import Achievement, compute_streaks


async def collect_counters(
    session: AsyncSession, user_id: UUID, *, today: date
) -> tuple[dict[str, int], int, int]:
    """Contadores de los logros y las rachas, en las unidades que espera
    `build_achievements`. Devuelve `(contadores, racha_actual, racha_más_larga)`."""
    all_food_dates = set(
        await session.scalars(
            select(FoodLog.log_date).where(FoodLog.user_id == user_id).distinct()
        )
    )
    current_streak, longest_streak = compute_streaks(all_food_dates, today=today)

    async def count(stmt) -> int:
        return await session.scalar(stmt) or 0

    counters = {
        "logging_days": len(all_food_dates),
        "longest_streak": longest_streak,
        "water_logging_days": await count(
            select(func.count(func.distinct(WaterLog.log_date))).where(
                WaterLog.user_id == user_id
            )
        ),
        "distinct_recipes": await count(
            select(func.count()).select_from(Recipe).where(Recipe.user_id == user_id)
        ),
        "distinct_foods": await count(
            select(func.count(func.distinct(FoodLog.food_id))).where(
                FoodLog.user_id == user_id, FoodLog.food_id.is_not(None)
            )
        ),
        "complete_days": await count(
            select(func.count()).select_from(
                select(FoodLog.log_date)
                .where(FoodLog.user_id == user_id)
                .group_by(FoodLog.log_date)
                .having(func.count(func.distinct(FoodLog.meal_type)) >= 3)
                .subquery()
            )
        ),
    }
    return counters, current_streak, longest_streak


async def sync_achievements(
    session: AsyncSession, user_id: UUID, achievements: list[Achievement], *, today: date
) -> tuple[dict[str, date], list[str]]:
    """Guarda los logros conseguidos que todavía no tuvieran fila y devuelve
    `({clave: fecha}, claves_nuevas)`.

    El INSERT es un upsert con `ON CONFLICT DO NOTHING` sobre `(user_id, key)`: dos
    pestañas abiertas pidiendo el resumen a la vez son dos peticiones concurrentes para el
    mismo logro recién conseguido, y sin esto la segunda reventaría contra el índice único
    (mismo caso que se corrigió en agua y perfil)."""
    existing: dict[str, date] = {
        row.key: row.earned_on
        for row in (
            await session.execute(
                select(UserAchievement.key, UserAchievement.earned_on).where(
                    UserAchievement.user_id == user_id
                )
            )
        ).all()
    }
    new_keys = [a.key for a in achievements if a.earned and a.key not in existing]
    if new_keys:
        await session.execute(
            pg_insert(UserAchievement)
            .values([{"user_id": user_id, "key": key, "earned_on": today} for key in new_keys])
            .on_conflict_do_nothing(index_elements=["user_id", "key"])
        )
        await session.commit()
        for key in new_keys:
            existing[key] = today
    return existing, new_keys
