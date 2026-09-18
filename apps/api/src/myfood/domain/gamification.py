"""Diseño ético de la gamificación (Fase 7, R10, documento 2 sección 23).

Reglas de implementación derivadas de R10, aplicadas aquí al pie de la
letra:
- El heatmap colorea por si hubo registro ese día, nunca por si se cumplió
  el objetivo calórico — `daily_activity_counts` ni siquiera mira kcal.
- La única racha es de registro constante (`current_streak`/
  `longest_streak`: días con AL MENOS un `food_log`), nunca de "días en
  objetivo" ni de "días en déficit".
- Los logros premian consistencia (rachas, agua) y variedad (recetas
  distintas), nunca resultado corporal — ninguno de los aquí definidos usa
  peso, calorías ni macros.
"""

from dataclasses import dataclass
from datetime import date, timedelta


def compute_streaks(log_dates: set[date], *, today: date) -> tuple[int, int]:
    """`(racha_actual, racha_más_larga)` a partir de los días (cualquier
    fecha, no solo recientes) en los que hubo registro. La racha actual
    cuenta hacia atrás desde hoy — un día sin registro todavía no la rompe
    hasta que termine (se permite no haber registrado today mismo)."""
    if not log_dates:
        return 0, 0

    longest = 0
    run = 0
    for offset in range((max(log_dates) - min(log_dates)).days + 1):
        day = min(log_dates) + timedelta(days=offset)
        if day in log_dates:
            run += 1
            longest = max(longest, run)
        else:
            run = 0

    current = 0
    cursor = today if today in log_dates else today - timedelta(days=1)
    while cursor in log_dates:
        current += 1
        cursor -= timedelta(days=1)

    return current, longest


@dataclass(frozen=True)
class Achievement:
    key: str
    title: str
    description: str
    earned: bool
    progress: int
    target: int


def build_achievements(
    *, longest_streak: int, water_logging_days: int, distinct_recipes: int
) -> list[Achievement]:
    return [
        Achievement(
            key="streak_7",
            title="Racha de 7 días",
            description="Registra tus comidas 7 días seguidos.",
            earned=longest_streak >= 7,
            progress=min(longest_streak, 7),
            target=7,
        ),
        Achievement(
            key="streak_30",
            title="Racha de 30 días",
            description="Registra tus comidas 30 días seguidos.",
            earned=longest_streak >= 30,
            progress=min(longest_streak, 30),
            target=30,
        ),
        Achievement(
            key="streak_100",
            title="Racha de 100 días",
            description="Registra tus comidas 100 días seguidos.",
            earned=longest_streak >= 100,
            progress=min(longest_streak, 100),
            target=100,
        ),
        Achievement(
            key="water_30_days",
            title="Bien hidratado",
            description="Registra agua en 30 días distintos.",
            earned=water_logging_days >= 30,
            progress=min(water_logging_days, 30),
            target=30,
        ),
        Achievement(
            key="recipes_10",
            title="Cocinillas",
            description="Crea 10 recetas distintas.",
            earned=distinct_recipes >= 10,
            progress=min(distinct_recipes, 10),
            target=10,
        ),
    ]
