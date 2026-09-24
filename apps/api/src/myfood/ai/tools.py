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
#
# El resto de campos son descripción, no cálculo: el modelo dice QUÉ tipo de cantidad ha
# entendido y si el plato le parece casero, y esas dos cosas cambian mucho el gramaje y las
# calorías (una tortilla casera no es la de Hacendado). Los gramos los sigue poniendo el
# backend a partir de ellos.
TIPOS_DE_CANTIDAD = (
    "porcion", "racion", "plato", "bol", "taza", "vaso", "cucharada", "cucharadita",
    "trozo", "rebanada", "loncha", "filete", "unidad", "punado", "lata", "gramos",
)  # fmt: skip
ORIGENES = ("casero", "envasado", "restaurante", "desconocido")

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
                    "tipo_cantidad": {
                        "type": "string",
                        "enum": list(TIPOS_DE_CANTIDAD),
                        "description": "En qué unidad está contada la cantidad.",
                    },
                    "tamano": {
                        "type": "string",
                        "enum": ["pequeno", "mediano", "grande"],
                        "description": "Respecto a una ración normal de ese alimento.",
                    },
                    "origen": {
                        "type": "string",
                        "enum": list(ORIGENES),
                        "description": (
                            "Si el plato es casero, de envase de supermercado o de "
                            "restaurante. Cambia bastante las calorías."
                        ),
                    },
                    "confianza": {"type": "string", "enum": ["alta", "media", "baja"]},
                    "motivo": {
                        "type": "string",
                        "maxLength": 160,
                        "description": "Por qué has elegido ESE alimento, en una frase.",
                    },
                    "alternativas": {
                        "type": "array",
                        "maxItems": 2,
                        "items": {"type": "string"},
                        "description": (
                            "Otros alias que encajarían, para que el usuario cambie de un "
                            "toque si te has equivocado."
                        ),
                    },
                },
            },
        },
        "pregunta": {
            "type": "string",
            "maxLength": 200,
            "description": (
                "Una sola pregunta al usuario si algo importante para acertar la cantidad "
                "está de verdad ambiguo. Déjala vacía si no hace falta."
            ),
        },
        "no_encontrados": {
            "type": "array",
            "maxItems": 5,
            "items": {"type": "string", "maxLength": 80},
            "description": (
                "Alimentos que el usuario ha mencionado y que NO están en candidates. "
                "Dilos en vez de callártelos: antes desaparecían sin que se enterase nadie "
                "y las calorías del día salían de menos."
            ),
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



DESCRIBE_PLATE_TOOL_NAME = "describe_plate"

# La fase de visión del registro por foto. El modelo DESCRIBE lo que ve; no calcula nada. Por
# eso no hay ningún campo de gramos ni de calorías aquí: `tipo_cantidad` + `cantidad` + `tamano`
# es lo que `domain/quantity_text.py` convierte después en un gramaje, exactamente igual que
# con lo que escribe el usuario a mano (R1).
DESCRIBE_PLATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["alimentos"],
    "properties": {
        "alimentos": {
            "type": "array",
            "maxItems": 12,
            "items": {
                "type": "object",
                "required": ["nombre", "cantidad", "tipo_cantidad"],
                "properties": {
                    "nombre": {
                        "type": "string",
                        "maxLength": 80,
                        "description": (
                            "El alimento a secas, en español y como se buscaría en un "
                            "recetario: «tortilla de patatas», «arroz blanco». Sin "
                            "coletillas ni paréntesis: con ellos no se encuentra nada."
                        ),
                    },
                    "cantidad": {"type": "number", "minimum": 0.1, "maximum": 20},
                    "tipo_cantidad": {"type": "string", "enum": list(TIPOS_DE_CANTIDAD)},
                    "tamano": {"type": "string", "enum": ["pequeno", "mediano", "grande"]},
                    "origen": {"type": "string", "enum": list(ORIGENES)},
                    "confianza": {"type": "string", "enum": ["alta", "media", "baja"]},
                    "pista_referencia": {
                        "type": "string",
                        "maxLength": 80,
                        "description": (
                            "Qué has usado para estimar el tamaño: el plato, un cubierto, "
                            "una mano, un vaso… Si no hay nada, dilo."
                        ),
                    },
                },
            },
        },
        "nota": {
            "type": "string",
            "maxLength": 200,
            "description": "Algo que el usuario deba saber para juzgar la estimación.",
        },
    },
}


def build_describe_plate_tool(sink: list[dict]) -> SdkMcpTool[Any]:
    """Fase de visión del registro por foto: qué hay en el plato y en qué cantidad."""

    @tool(
        DESCRIBE_PLATE_TOOL_NAME,
        "Describe los alimentos que se ven en la foto de un plato y en qué cantidad.",
        DESCRIBE_PLATE_SCHEMA,
    )
    async def _describe_plate(args: dict[str, Any]) -> dict[str, Any]:
        sink.append(args)
        return {"content": [{"type": "text", "text": "Plato descrito."}]}

    return _describe_plate


ESTIMATE_FOODS_TOOL_NAME = "estimate_foods"

# Respaldo cuando el catálogo no tiene el alimento. Aquí SÍ hay valores nutricionales, y es la
# excepción que ya existía para el chat: lo que no está en el catálogo entra con los números
# que pone el modelo y queda marcado como estimación (`entry_source='ai_estimate'`), nunca
# mezclado con el dato oficial. `fuente` es obligatoria en la práctica: si un número no viene
# del ETL, que se vea de dónde viene (R9).
ESTIMATE_FOODS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "required": ["nombre", "cantidad_texto", "kcal_100g"],
                "properties": {
                    "nombre": {"type": "string", "maxLength": 80},
                    "cantidad_texto": {"type": "string", "maxLength": 100},
                    "tipo_cantidad": {"type": "string", "enum": list(TIPOS_DE_CANTIDAD)},
                    "tamano": {"type": "string", "enum": ["pequeno", "mediano", "grande"]},
                    "kcal_100g": {"type": "number", "minimum": 0, "maximum": 900},
                    "protein_100g": {"type": "number", "minimum": 0, "maximum": 100},
                    "fat_100g": {"type": "number", "minimum": 0, "maximum": 100},
                    "carbs_100g": {"type": "number", "minimum": 0, "maximum": 100},
                    "fuente": {
                        "type": "string",
                        "maxLength": 200,
                        "description": "La URL de donde has sacado los valores.",
                    },
                },
            },
        },
    },
}


def build_estimate_foods_tool(sink: list[dict]) -> SdkMcpTool[Any]:
    """Valores por 100 g de un alimento que no está en el catálogo, con su fuente."""

    @tool(
        ESTIMATE_FOODS_TOOL_NAME,
        "Devuelve los valores nutricionales por 100 g de alimentos que no están en el "
        "catálogo, citando de dónde salen.",
        ESTIMATE_FOODS_SCHEMA,
    )
    async def _estimate_foods(args: dict[str, Any]) -> dict[str, Any]:
        sink.append(args)
        return {"content": [{"type": "text", "text": "Estimación recibida."}]}

    return _estimate_foods

SUGGEST_SUPPLEMENTS_TOOL_NAME = "suggest_supplements"


def suggest_supplements_schema(keys: tuple[str, ...]) -> dict[str, Any]:
    """`key` es un enum cerrado con la lista blanca: el modelo no puede nombrar otro suplemento."""
    return {
        "type": "object",
        "required": ["suggestions"],
        "properties": {
            "suggestions": {
                "type": "array",
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "required": ["key", "reason"],
                    "properties": {
                        "key": {"type": "string", "enum": list(keys)},
                        "reason": {"type": "string", "maxLength": 240},
                    },
                },
            }
        },
    }


def build_suggest_supplements_tool(sink: list[dict], keys: tuple[str, ...]) -> SdkMcpTool[Any]:
    """Sugerencia de suplementos (sección 10.7): el modelo elige claves de la lista blanca y
    razona con los datos; nunca propone una dosis."""

    @tool(
        SUGGEST_SUPPLEMENTS_TOOL_NAME,
        "Sugiere suplementos de la lista blanca cuando los datos de ingesta lo apoyan.",
        suggest_supplements_schema(keys),
    )
    async def _suggest_supplements(args: dict[str, Any]) -> dict[str, Any]:
        sink.append(args)
        return {"content": [{"type": "text", "text": "Sugerencias recibidas."}]}

    return _suggest_supplements
