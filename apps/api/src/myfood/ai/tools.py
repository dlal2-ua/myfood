"""Herramientas de function calling para iafood (secciones 10.3 y 10.8). En
cada flujo el LLM **solo** dispone de la herramienta de ese flujo — no hay
salida de texto libre que se interprete como datos (R1): la única forma de
que el modelo "diga" algo estructurado es llamando a la herramienta con los
alias de `candidates`.

Cada una se registra como servidor MCP en proceso
(`claude_agent_sdk.create_sdk_mcp_server`) con `tools=[]` en las opciones
del Agent SDK (sin herramientas nativas del CLI — Bash, Read, etc. —
deshabilitadas), así el modelo no tiene ninguna otra vía de actuar más que
la herramienta que se le da.
"""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import SdkMcpTool, tool

PROPOSE_MEAL_PLAN_TOOL_NAME = "propose_meal_plan"

_MEAL_TYPES = ["breakfast", "morning_snack", "lunch", "afternoon_snack", "dinner", "supper"]

# JSON Schema tal cual la sección 10.3 (approx_portion es intención de
# tamaño, NUNCA gramos — el optimizador de `domain/diet_engine.py` es quien
# decide las cantidades exactas).
PROPOSE_MEAL_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["days"],
    "properties": {
        "days": {
            "type": "array",
            "maxItems": 7,
            "items": {
                "type": "object",
                "required": ["day_index", "meals"],
                "properties": {
                    "day_index": {"type": "integer", "minimum": 0, "maximum": 6},
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
            },
        },
        "rationale": {"type": "string", "maxLength": 1200},
    },
}


def build_propose_meal_plan_tool(sink: list[dict]) -> SdkMcpTool[Any]:
    """`sink` recibe los argumentos ya validados contra el schema cada vez
    que el modelo llama a la herramienta — el llamador (`ai/flows/diet_plan.py`)
    lee `sink[-1]` tras agotar la respuesta de `query()`. No se valida nada
    de negocio aquí (alias reales, alérgenos...) — eso es `ai/validator.py`,
    después de esta llamada."""

    @tool(
        PROPOSE_MEAL_PLAN_TOOL_NAME,
        "Propone la estructura de un plan de comidas usando únicamente los "
        "alias de alimento facilitados en candidates.",
        PROPOSE_MEAL_PLAN_SCHEMA,
    )
    async def _propose_meal_plan(args: dict[str, Any]) -> dict[str, Any]:
        sink.append(args)
        return {"content": [{"type": "text", "text": "Plan recibido."}]}

    return _propose_meal_plan


RESOLVE_FOOD_ITEMS_TOOL_NAME = "resolve_food_items"

# `approx_quantity_text` es la cantidad tal y como la mencionó el usuario
# (o "ración habitual" si no dio ninguna) — texto libre, nunca un número
# que el LLM haya calculado (R1). `domain/quantity_text.py` es quien lo
# convierte a un gramaje de partida, siempre editable por el usuario antes
# de confirmar (sección 10.8).
RESOLVE_FOOD_ITEMS_SCHEMA: dict[str, Any] = {
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
                    "approx_quantity_text": {"type": "string", "maxLength": 100},
                },
            },
        },
    },
}


def build_resolve_food_items_tool(sink: list[dict]) -> SdkMcpTool[Any]:
    """Igual que `build_propose_meal_plan_tool` pero para Smart Log
    (sección 10.8): resuelve una frase en lenguaje natural a alimentos
    concretos de la lista de candidatos recuperada por RAG."""

    @tool(
        RESOLVE_FOOD_ITEMS_TOOL_NAME,
        "Resuelve una descripción de comida en lenguaje natural a alimentos "
        "concretos usando únicamente los alias de candidates.",
        RESOLVE_FOOD_ITEMS_SCHEMA,
    )
    async def _resolve_food_items(args: dict[str, Any]) -> dict[str, Any]:
        sink.append(args)
        return {"content": [{"type": "text", "text": "Alimentos resueltos."}]}

    return _resolve_food_items
