"""Flujo completo de generación de dietas con iafood (sección 10.6).

Dividido en dos mitades, cada una en el proceso que le corresponde (regla
19): `request_diet_plan` corre en el proceso `api` (todo determinista y
local: objetivos, candidatos, anonimización) y solo encola un aviso para
el `worker`; `process_diet_plan_job` corre en el `worker` y es la única
que llama al Claude Agent SDK.

```
POST /ai/diet-plan            (api)
  → consentimiento + cuotas + credencial configurada
  → calcula targets, candidatos, anonymize()
  → crea ai_session(status='running'), responde 202
  → encola en Redis
                                                    (worker)
  → decide qué credencial descifrada usar
  → llama al Agent SDK con la tool propose_meal_plan (máx. 2 intentos)
  → valida estructura + re-verifica alérgenos/restricciones (independiente)
  → resuelve gramos día a día (solve_day_with_fixed_items)
  → valida totales (kcal ±5%, proteína ≥90%, grasa mínima, suelo R6)
  → si OK: crea DietPlan (generated_by='iafood') + una ai_proposal por día
  → ai_session.status = 'succeeded' | 'rejected_validation' | 'failed'
```
"""

from __future__ import annotations

import random
import uuid
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from myfood.ai import client as ai_client
from myfood.ai import tools
from myfood.ai.agent import AiAgentError, run_agent
from myfood.ai.anonymize import build_diet_plan_payload
from myfood.ai.prompts import (
    DIET_PLAN_PROMPT_VERSION,
    DIET_PLAN_SYSTEM_V1,
    build_diet_plan_user_prompt,
)
from myfood.ai.queue import enqueue_diet_plan_job
from myfood.ai.validator import ValidationError, validate_day_totals, validate_structure
from myfood.db.models import AiProposal, AiSession, DietPlan
from myfood.db.session import AdminSessionLocal
from myfood.domain.diet_engine import (
    CandidateFood,
    DayPlan,
    DayTargets,
    solve_day_with_fixed_items,
)
from myfood.domain.food_candidates import (
    IAFOOD_POOL_PER_GROUP,
    sample_day_pool,
    select_candidates,
)
from myfood.domain.targets import ResolvedTargets, resolve_targets
from myfood.errors import AppError

_MAX_RETRY_ATTEMPTS = 2
_AGENT_TIMEOUT_SECONDS = 60.0

# Duplicado deliberadamente de `routers/diet_plans.py` (mismo patrón que
# `_day_targets` en `routers/water.py`): módulos independientes, la
# especificación acepta esta pequeña duplicación en vez de acoplar el
# flujo de iafood a las funciones "privadas" de otro router.
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


async def _resolve(session: AsyncSession, user_id: UUID) -> ResolvedTargets:
    return await resolve_targets(session, user_id, action="generar un plan")


async def request_diet_plan(session: AsyncSession, user_id: UUID, *, num_days: int) -> AiSession:
    """Corre en el proceso `api`. Nunca llama al proveedor de IA (regla 19)
    — solo prepara todo lo determinista y encola el trabajo real."""
    credential_status = await ai_client.get_credential_status(session)
    if not credential_status.configured:
        raise AppError(
            "AI_NOT_CONFIGURED",
            "El administrador todavía no ha configurado la credencial de iafood.",
            status_code=503,
        )

    resolved = await _resolve(session, user_id)
    profile, targets = resolved.profile, resolved.day_targets()
    meal_types = _meal_types_for(profile.meals_per_day)

    candidates = sample_day_pool(
        await select_candidates(session, user_id),
        random.Random(uuid.uuid4().hex),
        per_group=IAFOOD_POOL_PER_GROUP,
    )
    if not candidates:
        raise AppError(
            "NO_CANDIDATE_FOODS",
            "No hay suficientes alimentos disponibles con tus restricciones actuales.",
            status_code=422,
        )

    anonymized = await build_diet_plan_payload(
        session,
        profile=profile,
        targets=targets,
        meals_per_day=profile.meals_per_day,
        candidates=candidates,
    )

    ai_session = AiSession(
        user_id=user_id,
        kind="diet_plan",
        status="running",
        request_payload={
            "prompt_version": DIET_PLAN_PROMPT_VERSION,
            "num_days": num_days,
            "meal_types": meal_types,
            "anonymized": anonymized.payload,
            "alias_to_food_id": anonymized.alias_to_food_id,
        },
    )
    session.add(ai_session)
    await session.commit()
    await session.refresh(ai_session)

    await enqueue_diet_plan_job(str(ai_session.id))
    return ai_session


def _candidates_by_food_id(
    anonymized_payload: dict, alias_to_food_id: dict[str, str]
) -> dict[str, CandidateFood]:
    """Reconstruye los `CandidateFood` completos (kcal/macros) a partir del
    propio payload ya anonimizado — evita una segunda consulta a la BD: es
    exactamente el mismo dato de catálogo (no personal) que ya se envió."""
    out: dict[str, CandidateFood] = {}
    for candidate in anonymized_payload["candidates"]:
        food_id = alias_to_food_id[candidate["id"]]
        out[food_id] = CandidateFood(
            id=food_id,
            name_es=candidate["name"],
            kcal_100g=candidate["kcal_100g"],
            protein_100g=candidate["protein_100g"],
            fat_100g=candidate["fat_100g"],
            carbs_100g=candidate["carbs_100g"],
            category=candidate.get("category"),
        )
    return out


def _retry_prompt(original_prompt: str, errors: list[ValidationError]) -> str:
    error_lines = "\n".join(f"- {e.code}: {e.message}" for e in errors)
    return (
        f"{original_prompt}\n\nTu propuesta anterior no era válida:\n{error_lines}\n"
        "Corrígela y vuelve a llamar a propose_meal_plan con una propuesta distinta."
    )


async def process_diet_plan_job(ai_session_id: str) -> None:
    """Corre en el `worker` (regla 19) — la única función de todo el
    proyecto que invoca `ai/agent.run_agent` para el flujo de dietas."""
    async with AdminSessionLocal() as session:
        ai_session = await session.get(AiSession, uuid.UUID(ai_session_id))
        if ai_session is None or ai_session.status != "running":
            return  # ya procesado, o no existe (defensivo)

        user_id = ai_session.user_id
        request_payload = ai_session.request_payload
        alias_to_food_id: dict[str, str] = request_payload["alias_to_food_id"]
        num_days: int = request_payload["num_days"]
        meal_types: list[str] = request_payload["meal_types"]
        anonymized_payload: dict = request_payload["anonymized"]
        targets = DayTargets(**anonymized_payload["targets"])

        token = await ai_client.get_decrypted_token(session)
        if token is None:
            ai_session.status = "failed"
            ai_session.validation_errors = [
                {"code": "AI_NOT_CONFIGURED", "message": "La credencial se retiró tras encolar."}
            ]
            await session.commit()
            return

        resolved = await _resolve(session, user_id)
        safety_floor_kcal = resolved.safety_floor_kcal
        min_fat_g = resolved.min_fat_g

        candidate_by_food_id = _candidates_by_food_id(anonymized_payload, alias_to_food_id)
        base_prompt = build_diet_plan_user_prompt(anonymized_payload, num_days=num_days)

        plan_args: dict | None = None
        validation_errors: list[ValidationError] = []
        day_plans: dict[int, DayPlan] | None = None
        agent_result = None
        attempts = 0

        for attempt in range(1, _MAX_RETRY_ATTEMPTS + 1):
            attempts = attempt
            sink: list[dict] = []
            tool_obj = tools.build_propose_meal_plan_tool(sink)
            prompt = base_prompt if attempt == 1 else _retry_prompt(base_prompt, validation_errors)

            try:
                agent_result = await run_agent(
                    token=token,
                    prompt=prompt,
                    system_prompt=DIET_PLAN_SYSTEM_V1,
                    mcp_tools=[tool_obj],
                    max_turns=2,
                    timeout_seconds=_AGENT_TIMEOUT_SECONDS,
                )
            except AiAgentError as exc:
                ai_session.status = "failed"
                ai_session.attempts = attempts
                ai_session.validation_errors = [{"code": exc.code, "message": str(exc)}]
                await session.commit()
                return

            if not sink:
                validation_errors = [
                    ValidationError("NO_TOOL_CALL", "La IA no llamó a propose_meal_plan.")
                ]
                continue

            plan_args = sink[-1]
            struct_errors, resolved_by_day = await validate_structure(
                session,
                plan_args,
                alias_to_food_id=alias_to_food_id,
                user_id=user_id,
                expected_num_days=num_days,
                expected_meal_types=meal_types,
            )
            if struct_errors:
                validation_errors = struct_errors
                continue

            numeric_errors: list[ValidationError] = []
            candidate_day_plans: dict[int, DayPlan] = {}
            for day_index, meals in resolved_by_day.items():
                items_by_meal = {
                    meal_type: [candidate_by_food_id[fid] for fid in food_ids]
                    for meal_type, food_ids in meals.items()
                    if food_ids
                }
                day_plan = solve_day_with_fixed_items(items_by_meal, targets)
                if not day_plan.feasible:
                    numeric_errors.append(
                        ValidationError(
                            "DAY_INFEASIBLE", f"El día {day_index} no se pudo resolver."
                        )
                    )
                    continue
                day_errors = validate_day_totals(
                    day_plan.totals,
                    targets,
                    safety_floor_kcal=safety_floor_kcal,
                    min_fat_g=min_fat_g,
                )
                if day_errors:
                    numeric_errors.extend(day_errors)
                    continue
                candidate_day_plans[day_index] = day_plan

            if numeric_errors:
                validation_errors = numeric_errors
                continue

            day_plans = candidate_day_plans
            break

        if not day_plans:
            ai_session.status = "rejected_validation"
            ai_session.attempts = attempts
            ai_session.validation_errors = [
                {"code": e.code, "message": e.message} for e in validation_errors
            ]
            await session.commit()
            return

        plan = DietPlan(
            user_id=user_id,
            name="Plan iafood",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=num_days - 1),
            status="draft",
            target_kcal=targets.kcal,
            target_protein_g=targets.protein_g,
            target_fat_g=targets.fat_g,
            target_carbs_g=targets.carbs_g,
            generated_by="iafood",
        )
        session.add(plan)
        await session.flush()

        rationale = (plan_args or {}).get("rationale")
        for day_index, day_plan in day_plans.items():
            proposal_payload = {
                "diet_plan_id": str(plan.id),
                "day_index": day_index,
                "meals": [
                    {
                        "meal_type": meal.meal_type,
                        "items": [
                            {"food_id": item.food_id, "grams": item.grams} for item in meal.items
                        ],
                    }
                    for meal in day_plan.meals
                ],
            }
            session.add(
                AiProposal(
                    ai_session_id=ai_session.id,
                    user_id=user_id,
                    scope="meal",
                    payload=proposal_payload,
                    rationale=rationale,
                    status="pending",
                )
            )

        ai_session.status = "succeeded"
        ai_session.attempts = attempts
        ai_session.response_payload = {
            "diet_plan_id": str(plan.id),
            "days_proposed": len(day_plans),
        }
        ai_session.input_tokens = agent_result.input_tokens if agent_result else None
        ai_session.output_tokens = agent_result.output_tokens if agent_result else None
        await session.commit()
