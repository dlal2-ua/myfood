"""Diseño ético de la gamificación (Fase 7, R10, documento 2 sección 23).

Reglas de implementación derivadas de R10, aplicadas aquí al pie de la
letra:
- El heatmap colorea por si hubo registro ese día, nunca por si se cumplió
  el objetivo calórico — `daily_activity_counts` ni siquiera mira kcal.
- La única racha es de registro constante (`current_streak`/
  `longest_streak`: días con AL MENOS un `food_log`), nunca de "días en
  objetivo" ni de "días en déficit".
- Los logros premian constancia (rachas, agua, pesadas), variedad
  (alimentos y recetas distintos) y uso, nunca resultado corporal —
  ninguno de los aquí definidos mira peso, calorías ni macros. Una pesada
  cuenta por haberla anotado, diga lo que diga la báscula.

Cada logro lleva además su insignia: `icon` (qué dibuja el frontend),
`tier` (bronce/plata/oro, solo por lo que cuesta conseguirlo) y `family`
(para agrupar la pared de insignias). Son metadatos de presentación — la
condición de "conseguido" sigue siendo el mismo cálculo determinista.
"""

from dataclasses import dataclass
from datetime import date, timedelta

TIERS = ("bronze", "silver", "gold")


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
    icon: str
    tier: str
    family: str


@dataclass(frozen=True)
class _Definition:
    key: str
    title: str
    description: str
    target: int
    icon: str
    tier: str
    family: str
    counter: str


# El orden es el de la pared de insignias: por familia, y dentro de cada una de
# menos a más difícil.
DEFINITIONS: tuple[_Definition, ...] = (
    _Definition(
        key="first_log",
        title="Primer registro",
        description="Apunta tu primera comida.",
        target=1,
        icon="seedling",
        tier="bronze",
        family="logging",
        counter="logging_days",
    ),
    _Definition(
        key="logging_30_days",
        title="Un mes de registros",
        description="Apunta algo en 30 días distintos, seguidos o no.",
        target=30,
        icon="notebook",
        tier="silver",
        family="logging",
        counter="logging_days",
    ),
    _Definition(
        key="logging_180_days",
        title="Medio año contigo",
        description="Apunta algo en 180 días distintos.",
        target=180,
        icon="notebook",
        tier="gold",
        family="logging",
        counter="logging_days",
    ),
    _Definition(
        key="streak_7",
        title="Racha de 7 días",
        description="Registra tus comidas 7 días seguidos.",
        target=7,
        icon="flame",
        tier="bronze",
        family="streak",
        counter="longest_streak",
    ),
    _Definition(
        key="streak_30",
        title="Racha de 30 días",
        description="Registra tus comidas 30 días seguidos.",
        target=30,
        icon="flame",
        tier="silver",
        family="streak",
        counter="longest_streak",
    ),
    _Definition(
        key="streak_100",
        title="Racha de 100 días",
        description="Registra tus comidas 100 días seguidos.",
        target=100,
        icon="flame",
        tier="gold",
        family="streak",
        counter="longest_streak",
    ),
    _Definition(
        key="water_7_days",
        title="Primer sorbo",
        description="Registra agua en 7 días distintos.",
        target=7,
        icon="droplet",
        tier="bronze",
        family="water",
        counter="water_logging_days",
    ),
    _Definition(
        key="water_30_days",
        title="Bien hidratado",
        description="Registra agua en 30 días distintos.",
        target=30,
        icon="droplet",
        tier="silver",
        family="water",
        counter="water_logging_days",
    ),
    _Definition(
        key="variety_50_foods",
        title="Paladar curioso",
        description="Registra 50 alimentos distintos.",
        target=50,
        icon="apple",
        tier="bronze",
        family="variety",
        counter="distinct_foods",
    ),
    _Definition(
        key="variety_200_foods",
        title="De todo un poco",
        description="Registra 200 alimentos distintos.",
        target=200,
        icon="apple",
        tier="gold",
        family="variety",
        counter="distinct_foods",
    ),
    _Definition(
        key="recipes_3",
        title="Manos a la masa",
        description="Crea 3 recetas.",
        target=3,
        icon="chef",
        tier="bronze",
        family="recipes",
        counter="distinct_recipes",
    ),
    _Definition(
        key="recipes_10",
        title="Cocinillas",
        description="Crea 10 recetas distintas.",
        target=10,
        icon="chef",
        tier="silver",
        family="recipes",
        counter="distinct_recipes",
    ),
    _Definition(
        key="complete_days_10",
        title="Día completo",
        description="Apunta las tres comidas principales en 10 días distintos.",
        target=10,
        icon="sun",
        tier="bronze",
        family="complete",
        counter="complete_days",
    ),
    _Definition(
        key="complete_days_60",
        title="Sin saltarte ninguna",
        description="Apunta las tres comidas principales en 60 días distintos.",
        target=60,
        icon="sun",
        tier="gold",
        family="complete",
        counter="complete_days",
    ),
)


def build_achievements(**counters: int) -> list[Achievement]:
    """Evalúa todas las definiciones contra los contadores que se le pasen. Un contador
    que falte cuenta como 0 — así añadir un logro nuevo nunca rompe a quien ya llamaba
    a esta función con los contadores viejos."""
    return [
        Achievement(
            key=d.key,
            title=d.title,
            description=d.description,
            earned=counters.get(d.counter, 0) >= d.target,
            progress=min(counters.get(d.counter, 0), d.target),
            target=d.target,
            icon=d.icon,
            tier=d.tier,
            family=d.family,
        )
        for d in DEFINITIONS
    ]


def achievement_title(key: str) -> str | None:
    return next((d.title for d in DEFINITIONS if d.key == key), None)
