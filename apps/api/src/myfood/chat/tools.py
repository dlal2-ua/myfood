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
from myfood.domain import diary_proposal
from myfood.domain.diet_engine import CandidateFood
from myfood.domain.food_candidates import EXCLUDE_RESTRICTED_SQL
from myfood.search import search_foods as meili_search_foods

READ_PANTRY_TOOL_NAME = "read_pantry"
SEARCH_FOODS_TOOL_NAME = "search_foods"
READ_PLAN_DAY_TOOL_NAME = "read_plan_day"
PROPOSE_DAY_CHANGE_TOOL_NAME = "propose_day_change"
ADD_TO_PANTRY_TOOL_NAME = "add_to_pantry"

_MEAL_TYPES = ["breakfast", "morning_snack", "lunch", "afternoon_snack", "dinner", "supper"]


def _alias_for(alias_map: dict[str, CandidateFood], candidate: CandidateFood) -> str:
    """Alias efímero del alimento; si ya tiene uno en este turno (porque salió
    antes en `search_foods` o en `read_plan_day`) se reutiliza en vez de crear
    un duplicado, para que el modelo vea siempre el mismo `cN` por alimento."""
    for alias, existing in alias_map.items():
        if existing.id == candidate.id:
            return alias
    alias = f"c{len(alias_map) + 1}"
    alias_map[alias] = candidate
    return alias


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
            alias = _alias_for(
                alias_map,
                CandidateFood(
                    id=str(row.id),
                    name_es=row.name_es,
                    kcal_100g=float(row.kcal_100g),
                    protein_100g=float(row.protein_100g),
                    fat_100g=float(row.fat_100g),
                    carbs_100g=float(row.carbs_100g),
                    category=row.category,
                ),
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


def _build_read_plan_day_tool(
    session: AsyncSession, user_id: UUID, alias_map: dict[str, CandidateFood]
) -> SdkMcpTool[Any]:
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
                    SELECT pm.meal_type, pm.sort_order, pi.food_id, f.name_es AS food_name,
                           f.category, fn.kcal_100g, fn.protein_100g, fn.fat_100g,
                           fn.carbs_100g, r.name AS recipe_name, pi.grams
                    FROM plan_days pd
                    JOIN plan_meals pm ON pm.plan_day_id = pd.id
                    JOIN plan_items pi ON pi.plan_meal_id = pm.id
                    LEFT JOIN foods f ON f.id = pi.food_id
                    LEFT JOIN food_nutrients fn ON fn.food_id = pi.food_id
                    LEFT JOIN recipes r ON r.id = pi.recipe_id
                    WHERE pd.plan_id = :plan_id AND pd.day_index = :day_index
                    ORDER BY pm.sort_order, coalesce(f.name_es, r.name), pi.id
                """),
                {"plan_id": str(plan.id), "day_index": day_index},
            )
        ).all()

        meals: dict[str, list[dict]] = {}
        for row in rows:
            meal_items = meals.setdefault(row.meal_type, [])
            if row.food_id is None:
                # Receta de batch cooking: no es un alimento y no se puede
                # referenciar por alias (el validador de cambios de día la
                # protege, ver `chat/flow.py`).
                meal_items.append(
                    {"name": row.recipe_name, "grams": float(row.grams), "is_recipe": True}
                )
                continue
            # Alias del alimento que YA está en el plan: así, para las comidas
            # que no cambia, el modelo los reutiliza en `propose_day_change` en
            # vez de tener que volver a buscar cada uno con `search_foods`
            # (con 5 llamadas por turno no llegaba en un día con 6 alimentos).
            alias = _alias_for(
                alias_map,
                CandidateFood(
                    id=str(row.food_id),
                    name_es=row.food_name,
                    kcal_100g=float(row.kcal_100g),
                    protein_100g=float(row.protein_100g),
                    fat_100g=float(row.fat_100g),
                    carbs_100g=float(row.carbs_100g),
                    category=row.category,
                ),
            )
            meal_items.append({"alias": alias, "name": row.food_name, "grams": float(row.grams)})

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


# --------------------------------------------------------------------------- diario

READ_DIARY_TOOL_NAME = "read_diary_day"
LOG_MEAL_TOOL_NAME = "propose_diary_entries"
EDIT_ENTRY_TOOL_NAME = "propose_diary_edit"

_READ_DIARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["date"],
    "properties": {"date": {"type": "string", "format": "date"}},
}


def _build_read_diary_tool(session: AsyncSession, user_id: UUID) -> SdkMcpTool[Any]:
    @tool(
        READ_DIARY_TOOL_NAME,
        "Lee lo que el usuario YA tiene apuntado en su diario ese día, con sus calorías y "
        "macros y el identificador de cada entrada. Úsalo antes de corregir o borrar algo, y "
        "para responder a preguntas sobre lo que lleva comido.",
        _READ_DIARY_SCHEMA,
    )
    async def _read_diary(args: dict[str, Any]) -> dict[str, Any]:
        try:
            day = date.fromisoformat(str(args.get("date")))
        except (TypeError, ValueError):
            return {"content": [{"type": "text", "text": "Fecha no válida."}]}
        entries = await diary_proposal.read_day(session, user_id, day)
        totals = {
            key: round(sum(e[key] for e in entries), 1)
            for key in ("kcal", "protein_g", "fat_g", "carbs_g")
        }
        payload = {"date": day.isoformat(), "entries": entries, "totals": totals}
        return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}

    return _read_diary


LOG_MEAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["date", "meal_type", "items"],
    "properties": {
        "date": {"type": "string", "format": "date"},
        "meal_type": {
            "type": "string",
            "enum": [
                "breakfast", "morning_snack", "lunch",
                "afternoon_snack", "dinner", "supper",
            ],
        },
        "request": {
            "type": "string",
            "description": "Lo que pidió el usuario, con sus palabras, para la confirmación.",
        },
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "alias": {
                        "type": "string",
                        "description": (
                            "Alias de un candidate de search_foods. Preferible SIEMPRE: con "
                            "él, las calorías salen del dato oficial y no de ti."
                        ),
                    },
                    "quantity_text": {
                        "type": "string",
                        "description": "Cuánto, con palabras: «dos rebanadas», «un vaso», «30 g».",
                    },
                    "name": {
                        "type": "string",
                        "description": "Solo si NO hay alias: cómo se llama el ingrediente.",
                    },
                    "grams": {"type": "number", "description": "Solo si no hay alias."},
                    "kcal_100g": {"type": "number", "description": "Solo si no hay alias."},
                    "protein_100g": {"type": "number"},
                    "fat_100g": {"type": "number"},
                    "carbs_100g": {"type": "number"},
                },
            },
        },
    },
}


def _build_log_meal_tool(sink: list[dict]) -> SdkMcpTool[Any]:
    @tool(
        LOG_MEAL_TOOL_NAME,
        "Propone apuntar alimentos en el diario del usuario. Un plato compuesto se "
        "descompone en sus ingredientes, uno por elemento de `items`. Para cada ingrediente, "
        "busca antes con search_foods y usa su `alias`; solo si de verdad no existe nada "
        "parecido, pon `name`, `grams` y los valores por 100 g, que quedarán marcados como "
        "estimación tuya. No se guarda nada hasta que el usuario lo confirme.",
        LOG_MEAL_SCHEMA,
    )
    async def _log_meal(args: dict[str, Any]) -> dict[str, Any]:
        sink.append(args)
        return {"content": [{"type": "text", "text": "Preparado, pendiente de confirmar."}]}

    return _log_meal


EDIT_ENTRY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["changes"],
    "properties": {
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["entry_id", "action"],
                "properties": {
                    "entry_id": {
                        "type": "string",
                        "description": "El que devuelve read_diary_day, nunca inventado.",
                    },
                    "action": {"type": "string", "enum": ["delete", "update"]},
                    "grams": {"type": "number"},
                    "meal_type": {
                        "type": "string",
                        "enum": [
                            "breakfast", "morning_snack", "lunch",
                            "afternoon_snack", "dinner", "supper",
                        ],
                    },
                },
            },
        },
    },
}


def _build_edit_entry_tool(sink: list[dict]) -> SdkMcpTool[Any]:
    @tool(
        EDIT_ENTRY_TOOL_NAME,
        "Propone corregir o borrar entradas que YA están en el diario. Lee antes el día con "
        "read_diary_day para tener los identificadores. No se aplica nada sin confirmación.",
        EDIT_ENTRY_SCHEMA,
    )
    async def _edit_entry(args: dict[str, Any]) -> dict[str, Any]:
        sink.append(args)
        return {"content": [{"type": "text", "text": "Preparado, pendiente de confirmar."}]}

    return _edit_entry


LOG_WATER_TOOL_NAME = "propose_water"

_LOG_WATER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["ml"],
    "properties": {
        "date": {"type": "string", "format": "date"},
        "ml": {"type": "number", "description": "Un vaso son 200 ml; una botella, 500."},
    },
}


def _build_log_water_tool(sink: list[dict]) -> SdkMcpTool[Any]:
    @tool(
        LOG_WATER_TOOL_NAME,
        "Propone apuntar agua bebida. No se guarda hasta que el usuario lo confirme.",
        _LOG_WATER_SCHEMA,
    )
    async def _log_water(args: dict[str, Any]) -> dict[str, Any]:
        sink.append(args)
        return {"content": [{"type": "text", "text": "Preparado, pendiente de confirmar."}]}

    return _log_water


ADD_TO_SHOPPING_LIST_TOOL_NAME = "propose_shopping_list"

_SHOPPING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["text"],
                "properties": {
                    "text": {"type": "string"},
                    "alias": {"type": "string", "description": "Si viene de search_foods."},
                },
            },
        },
    },
}


def _build_shopping_list_tool(sink: list[dict]) -> SdkMcpTool[Any]:
    @tool(
        ADD_TO_SHOPPING_LIST_TOOL_NAME,
        "Propone añadir cosas a la lista de la compra del usuario.",
        _SHOPPING_SCHEMA,
    )
    async def _shopping(args: dict[str, Any]) -> dict[str, Any]:
        sink.append(args)
        return {"content": [{"type": "text", "text": "Preparado, pendiente de confirmar."}]}

    return _shopping


def build_chat_tools(
    session: AsyncSession,
    user_id: UUID,
    *,
    alias_map: dict[str, CandidateFood],
    day_change_sink: list[dict],
    pantry_sink: list[dict],
    # Opcionales: quien solo quiera las herramientas de lectura (los tests de alias, por
    # ejemplo) no tiene por qué montar un recipiente para cada propuesta.
    diary_sink: list[dict] | None = None,
    edit_sink: list[dict] | None = None,
    water_sink: list[dict] | None = None,
    shopping_sink: list[dict] | None = None,
) -> list[SdkMcpTool[Any]]:
    diary_sink = [] if diary_sink is None else diary_sink
    edit_sink = [] if edit_sink is None else edit_sink
    water_sink = [] if water_sink is None else water_sink
    shopping_sink = [] if shopping_sink is None else shopping_sink
    return [
        _build_read_pantry_tool(session, user_id),
        _build_search_foods_tool(session, user_id, alias_map),
        _build_read_diary_tool(session, user_id),
        _build_read_plan_day_tool(session, user_id, alias_map),
        _build_log_meal_tool(diary_sink),
        _build_edit_entry_tool(edit_sink),
        _build_log_water_tool(water_sink),
        _build_shopping_list_tool(shopping_sink),
        _build_propose_day_change_tool(day_change_sink),
        _build_add_to_pantry_tool(pantry_sink),
    ]
