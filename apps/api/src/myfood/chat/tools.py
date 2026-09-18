"""Herramientas de function calling del chat conversacional (sección 24.2)
— distintas de las de `ai/tools.py`: aquí Claude puede encadenar varias
llamadas de solo lectura antes de responder o proponer algo (sección 24.3),
así que estas SÍ ejecutan trabajo real contra la BD (no solo `sink.append`
como el resto de iafood) y le devuelven el resultado al modelo para que
decida el siguiente paso.

Corren siempre en el `worker`, dentro de la misma `AdminSessionLocal` que
abre `chat/flow.py::process_chat_job` (regla 19) — sin contexto RLS, así
que cada consulta filtra `user_id` a mano, igual que el resto de código que
usa `AdminSessionLocal` (p. ej. `ai/flows/diet_plan.py`).

`read_pantry` / `search_foods` / `read_plan_day` nunca devuelven `food_id`
reales al modelo (R5) — los mismos alias efímeros `c1`, `c2`... que usa
`ai/anonymize.py` para el resto de iafood, aquí asignados sobre la marcha a
medida que `search_foods` va trayendo resultados a lo largo del turno
(`alias_map` se comparte entre todas las llamadas de un mismo turno, nunca
se reinicia a mitad de turno). El mapeo alias→alimento solo vive en memoria
del proceso `worker` durante ese turno; nunca sale del servidor.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any
from uuid import UUID

from claude_agent_sdk import SdkMcpTool, tool
from sqlalchemy import bindparam, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import DietPlan, Food, PantryItem
from myfood.domain.diet_engine import CandidateFood
from myfood.domain.food_candidates import EXCLUDE_RESTRICTED_SQL
from myfood.search import search_foods as meili_search_foods

READ_PANTRY_TOOL_NAME = "read_pantry"
SEARCH_FOODS_TOOL_NAME = "search_foods"
READ_PLAN_DAY_TOOL_NAME = "read_plan_day"
PROPOSE_DAY_CHANGE_TOOL_NAME = "propose_day_change"
ADD_TO_PANTRY_TOOL_NAME = "add_to_pantry"

_MEAL_TYPES = ["breakfast", "morning_snack", "lunch", "afternoon_snack", "dinner", "supper"]


def _build_read_pantry_tool(session: AsyncSession, user_id: UUID) -> SdkMcpTool[Any]:
    @tool(
        READ_PANTRY_TOOL_NAME,
        "Lee la despensa actual del usuario.",
        {"type": "object", "properties": {}},
    )
    async def _read_pantry(_args: dict[str, Any]) -> dict[str, Any]:
        rows = (
            await session.execute(
                select(PantryItem, Food.name_es)
                .join(Food, Food.id == PantryItem.food_id)
                .where(PantryItem.user_id == user_id)
                .order_by(Food.name_es)
            )
        ).all()
        items = [
            {
                "name": name_es,
                "quantity_g": float(item.quantity_g),
                "expires_on": item.expires_on.isoformat() if item.expires_on else None,
            }
            for item, name_es in rows
        ]
        text_out = json.dumps({"items": items}, ensure_ascii=False)
        return {"content": [{"type": "text", "text": text_out}]}

    return _read_pantry


_SEARCH_FOODS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["query"],
    "properties": {
        "query": {"type": "string"},
        "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 20},
    },
}


def _build_search_foods_tool(
    session: AsyncSession, user_id: UUID, alias_map: dict[str, CandidateFood]
) -> SdkMcpTool[Any]:
    @tool(
        SEARCH_FOODS_TOOL_NAME,
        "Busca alimentos reales en la base de datos por nombre. "
        "Devuelve candidatos con alias efímeros, nunca IDs reales.",
        _SEARCH_FOODS_SCHEMA,
    )
    async def _search_foods(args: dict[str, Any]) -> dict[str, Any]:
        query = args["query"]
        limit = int(args.get("limit") or 10)
        hits, _total = await meili_search_foods(query, None, limit, 0)
        ids = [hit["id"] for hit in hits]
        if not ids:
            return {"content": [{"type": "text", "text": json.dumps({"candidates": []})}]}

        stmt = text(f"""
            SELECT f.id, f.name_es, f.category, fn.kcal_100g, fn.protein_100g,
                   fn.fat_100g, fn.carbs_100g
            FROM foods f
            JOIN food_nutrients fn ON fn.food_id = f.id
            WHERE f.id IN :ids AND {EXCLUDE_RESTRICTED_SQL}
        """).bindparams(bindparam("ids", expanding=True))
        rows = (await session.execute(stmt, {"ids": ids, "user_id": str(user_id)})).all()

        candidates_out = []
        for row in rows:
            alias = f"c{len(alias_map) + 1}"
            alias_map[alias] = CandidateFood(
                id=str(row.id),
                name_es=row.name_es,
                kcal_100g=float(row.kcal_100g),
                protein_100g=float(row.protein_100g),
                fat_100g=float(row.fat_100g),
                carbs_100g=float(row.carbs_100g),
                category=row.category,
            )
            candidates_out.append({"id": alias, "name": row.name_es, "category": row.category})
        text_out = json.dumps({"candidates": candidates_out}, ensure_ascii=False)
        return {"content": [{"type": "text", "text": text_out}]}

    return _search_foods


_READ_PLAN_DAY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["date"],
    "properties": {"date": {"type": "string", "format": "date"}},
}


def _build_read_plan_day_tool(session: AsyncSession, user_id: UUID) -> SdkMcpTool[Any]:
    @tool(
        READ_PLAN_DAY_TOOL_NAME,
        "Lee las comidas planeadas para una fecha concreta.",
        _READ_PLAN_DAY_SCHEMA,
    )
    async def _read_plan_day(args: dict[str, Any]) -> dict[str, Any]:
        try:
            target_date = date.fromisoformat(args["date"])
        except ValueError:
            text_out = json.dumps({"error": "INVALID_DATE", "meals": {}})
            return {"content": [{"type": "text", "text": text_out}]}

        plan = await session.scalar(
            select(DietPlan).where(DietPlan.user_id == user_id, DietPlan.status == "active")
        )
        if plan is None:
            return {
                "content": [
                    {"type": "text", "text": json.dumps({"error": "NO_ACTIVE_PLAN", "meals": {}})}
                ]
            }
        day_index = (target_date - plan.start_date).days
        if day_index < 0 or (plan.end_date is not None and target_date > plan.end_date):
            text_out = json.dumps({"error": "DATE_OUT_OF_RANGE", "meals": {}})
            return {"content": [{"type": "text", "text": text_out}]}

        rows = (
            await session.execute(
                text("""
                    SELECT pm.meal_type, pm.sort_order, f.name_es AS food_name,
                           r.name AS recipe_name, pi.grams
                    FROM plan_days pd
                    JOIN plan_meals pm ON pm.plan_day_id = pd.id
                    JOIN plan_items pi ON pi.plan_meal_id = pm.id
                    LEFT JOIN foods f ON f.id = pi.food_id
                    LEFT JOIN recipes r ON r.id = pi.recipe_id
                    WHERE pd.plan_id = :plan_id AND pd.day_index = :day_index
                    ORDER BY pm.sort_order
                """),
                {"plan_id": str(plan.id), "day_index": day_index},
            )
        ).all()

        meals: dict[str, list[dict]] = {}
        for row in rows:
            meal_items = meals.setdefault(row.meal_type, [])
            meal_items.append({"name": row.food_name or row.recipe_name, "grams": float(row.grams)})

        return {
            "content": [
                {"type": "text", "text": json.dumps({"meals": meals}, ensure_ascii=False)}
            ]
        }

    return _read_plan_day


PROPOSE_DAY_CHANGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["date", "meals"],
    "properties": {
        "date": {"type": "string", "format": "date"},
        "meals": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["meal_type", "items"],
                "properties": {
                    "meal_type": {"type": "string", "enum": _MEAL_TYPES},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["alias", "approx_portion"],
                            "properties": {
                                "alias": {"type": "string"},
                                "approx_portion": {
                                    "type": "string",
                                    "enum": ["small", "medium", "large"],
                                },
                            },
                        },
                    },
                },
            },
        },
    },
}


def _build_propose_day_change_tool(sink: list[dict]) -> SdkMcpTool[Any]:
    @tool(
        PROPOSE_DAY_CHANGE_TOOL_NAME,
        "Propone cambios para UNA fecha concreta. Usa solo alias de "
        "candidates ya recuperados con search_foods. Nunca gramos ni kcal.",
        PROPOSE_DAY_CHANGE_SCHEMA,
    )
    async def _propose_day_change(args: dict[str, Any]) -> dict[str, Any]:
        sink.append(args)
        return {"content": [{"type": "text", "text": "Cambio recibido."}]}

    return _propose_day_change


ADD_TO_PANTRY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["alias", "approx_quantity_text"],
                "properties": {
                    "alias": {"type": "string"},
                    "approx_quantity_text": {"type": "string"},
                },
            },
        },
    },
}


def _build_add_to_pantry_tool(sink: list[dict]) -> SdkMcpTool[Any]:
    @tool(
        ADD_TO_PANTRY_TOOL_NAME,
        "Añade alimentos mencionados por el usuario a su despensa. "
        "Usa solo alias de candidates ya recuperados con search_foods.",
        ADD_TO_PANTRY_SCHEMA,
    )
    async def _add_to_pantry(args: dict[str, Any]) -> dict[str, Any]:
        sink.append(args)
        text_out = "Añadido a la despensa (pendiente de confirmar)."
        return {"content": [{"type": "text", "text": text_out}]}

    return _add_to_pantry


def build_chat_tools(
    session: AsyncSession,
    user_id: UUID,
    *,
    alias_map: dict[str, CandidateFood],
    day_change_sink: list[dict],
    pantry_sink: list[dict],
) -> list[SdkMcpTool[Any]]:
    return [
        _build_read_pantry_tool(session, user_id),
        _build_search_foods_tool(session, user_id, alias_map),
        _build_read_plan_day_tool(session, user_id),
        _build_propose_day_change_tool(day_change_sink),
        _build_add_to_pantry_tool(pantry_sink),
    ]
