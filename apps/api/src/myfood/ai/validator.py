"""Validador determinista de iafood (R1/sección 10.5) — el guardián. Se
ejecuta siempre, sin excepción, antes de crear ninguna `ai_proposal`. Un
plan que no pasa esta validación nunca llega al usuario.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.domain.diet_engine import DayTargets
from myfood.domain.food_candidates import EXCLUDE_RESTRICTED_SQL

# abs(kcal_real - target) <= este porcentaje del objetivo (sección 10.5).
KCAL_TOLERANCE_PCT = 0.05
# protein_real >= este porcentaje del objetivo.
MIN_PROTEIN_PCT_OF_TARGET = 0.90


@dataclass
class ValidationError:
    code: str
    message: str


async def validate_structure(
    session: AsyncSession,
    plan_args: dict,
    *,
    alias_to_food_id: dict[str, str],
    user_id: UUID,
    expected_num_days: int,
    expected_meal_types: list[str],
) -> tuple[list[ValidationError], dict[int, dict[str, list[str]]]]:
    """Comprueba (1) que todos los alias existen en el mapa de la sesión,
    (2)/(3) que ninguno de los alimentos resueltos tiene un alérgeno o
    restricción del usuario — re-verificado de forma independiente contra
    la BD, no solo confiando en que la selección de candidatos ya los
    excluyó — y (4) que la estructura (días/comidas) coincide con lo
    pedido. Devuelve además `food_ids_by_day_and_meal`, listo para pasar al
    optimizador (`domain/diet_engine.solve_day_with_fixed_items`) cuando no
    hay errores.
    """
    errors: list[ValidationError] = []
    days = plan_args.get("days") or []
    if len(days) != expected_num_days:
        errors.append(
            ValidationError(
                "STRUCTURE_MISMATCH",
                f"Se esperaban {expected_num_days} día(s), la IA propuso {len(days)}.",
            )
        )

    resolved: dict[int, dict[str, list[str]]] = {}
    unknown_aliases: set[str] = set()
    all_food_ids: set[str] = set()

    for day in days:
        day_index = day.get("day_index")
        meals_by_type: dict[str, list[str]] = {}
        for meal in day.get("meals", []):
            meal_type = meal.get("meal_type")
            if meal_type not in expected_meal_types:
                errors.append(
                    ValidationError(
                        "UNKNOWN_MEAL_TYPE", f"'{meal_type}' no es una comida esperada."
                    )
                )
                continue
            food_ids: list[str] = []
            for item in meal.get("items", []):
                alias = item.get("alias")
                food_id = alias_to_food_id.get(alias)
                if food_id is None:
                    unknown_aliases.add(str(alias))
                    continue
                food_ids.append(food_id)
                all_food_ids.add(food_id)
            meals_by_type[meal_type] = food_ids
        resolved[day_index] = meals_by_type

    if unknown_aliases:
        errors.append(
            ValidationError(
                "UNKNOWN_ALIAS",
                "La IA referenció alimentos fuera de la lista de candidatos: "
                f"{sorted(unknown_aliases)}.",
            )
        )

    if all_food_ids:
        stmt = text(f"""
            SELECT f.id FROM foods f
            WHERE f.id IN :food_ids
              AND NOT ({EXCLUDE_RESTRICTED_SQL})
        """).bindparams(bindparam("food_ids", expanding=True))
        restricted_rows = (
            await session.execute(stmt, {"food_ids": list(all_food_ids), "user_id": str(user_id)})
        ).all()
        if restricted_rows:
            errors.append(
                ValidationError(
                    "RESTRICTED_FOOD_SELECTED",
                    "La IA propuso alimentos con alérgenos o restricciones del usuario "
                    f"({len(restricted_rows)}).",
                )
            )

    return errors, resolved


def validate_day_totals(
    actual: DayTargets,
    targets: DayTargets,
    *,
    safety_floor_kcal: float,
    min_fat_g: float,
) -> list[ValidationError]:
    """Comprueba los totales YA calculados por el optimizador (sección 10.5,
    punto 5) — kcal dentro de tolerancia, proteína mínima, grasa mínima
    hormonal, y el suelo de seguridad calórico (R6), que nunca se puede
    saltar desde iafood."""
    errors: list[ValidationError] = []
    if abs(actual.kcal - targets.kcal) > KCAL_TOLERANCE_PCT * targets.kcal:
        errors.append(
            ValidationError(
                "KCAL_OUT_OF_RANGE",
                f"kcal {actual.kcal} se desvía más de un {KCAL_TOLERANCE_PCT:.0%} "
                f"del objetivo {targets.kcal}.",
            )
        )
    if actual.protein_g < MIN_PROTEIN_PCT_OF_TARGET * targets.protein_g:
        errors.append(
            ValidationError(
                "PROTEIN_TOO_LOW",
                f"proteína {actual.protein_g}g por debajo del "
                f"{MIN_PROTEIN_PCT_OF_TARGET:.0%} del objetivo {targets.protein_g}g.",
            )
        )
    if actual.fat_g < min_fat_g:
        errors.append(
            ValidationError(
                "FAT_BELOW_HORMONAL_MINIMUM",
                f"grasa {actual.fat_g}g por debajo del mínimo hormonal {min_fat_g}g.",
            )
        )
    if actual.kcal < safety_floor_kcal:
        errors.append(
            ValidationError(
                "BELOW_SAFETY_FLOOR",
                f"kcal {actual.kcal} por debajo del suelo de seguridad "
                f"de {safety_floor_kcal} (R6).",
            )
        )
    return errors
