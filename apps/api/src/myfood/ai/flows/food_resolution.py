"""Resolución de alimentos a partir de texto libre (RAG + function
calling), compartida por Smart Log (sección 10.8) y la importación de
recetas (sección 20: "cada línea de ingrediente... pasa por el mismo
resolutor que Smart Log"). Vive en su propio módulo para que ninguno de
los dos flujos dependa del otro.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from myfood.ai import tools
from myfood.ai.agent import AgentResult, run_agent
from myfood.db.models import Food
from myfood.domain.food_mentions import split_into_food_mentions
from myfood.domain.quantity_text import resolve_grams
from myfood.search import search_foods

# Alimentos por mención (ver `domain/food_mentions.py`) y tope total tras
# fusionar — una frase con muchas menciones no debe inflar sin límite el
# payload que se envía al LLM.
HITS_PER_MENTION = 8
CANDIDATE_LIMIT = 20


async def search_candidates_for_text(text: str) -> list[dict]:
    """RAG: la frase completa casi nunca coincide con ningún alimento real
    en Meilisearch (comprobado contra el catálogo real — ver
    `domain/food_mentions.py`), así que se busca cada mención por separado
    y se fusionan los resultados, deduplicados por id."""
    seen: dict[str, dict] = {}
    for mention in split_into_food_mentions(text):
        hits, _total = await search_foods(mention, kind=None, limit=HITS_PER_MENTION, offset=0)
        for hit in hits:
            seen.setdefault(hit["id"], hit)
    return list(seen.values())[:CANDIDATE_LIMIT]


def build_candidates_payload(hits: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """Alias efímeros para los candidatos recuperados — mismo criterio que
    `ai/anonymize.py` para el plan de dieta, aunque aquí no hay datos
    personales que anonimizar (solo nombres de alimentos, dato de
    catálogo)."""
    alias_to_food_id: dict[str, str] = {}
    candidates_out = []
    for index, hit in enumerate(hits, start=1):
        alias = f"c{index}"
        alias_to_food_id[alias] = hit["id"]
        candidates_out.append(
            {"id": alias, "name": hit["name_es"], "category": hit.get("category")}
        )
    return candidates_out, alias_to_food_id


async def resolve_food_mentions(
    session: AsyncSession,
    *,
    token: str,
    prompt: str,
    system_prompt: str,
    alias_to_food_id: dict[str, str],
    max_turns: int = 2,
    timeout_seconds: float = 30.0,
) -> tuple[list[dict], AgentResult]:
    """Llama al Agent SDK con `resolve_food_items` y resuelve cada alias
    devuelto a un `food_id` real + un gramaje de partida (R1 — nunca
    gramos calculados por la IA). Puede lanzar `AiAgentError`; el llamador
    decide qué hacer con su propia `ai_session` (Smart Log y la
    importación de recetas fallan de forma independiente)."""
    sink: list[dict] = []
    tool_obj = tools.build_resolve_food_items_tool(sink)

    agent_result = await run_agent(
        token=token,
        prompt=prompt,
        system_prompt=system_prompt,
        mcp_tools=[tool_obj],
        max_turns=max_turns,
        timeout_seconds=timeout_seconds,
    )

    items_out: list[dict] = []
    if sink:
        for item in sink[-1].get("items", []):
            food_id = alias_to_food_id.get(item.get("alias"))
            if food_id is None:
                continue  # alias inventado por el LLM (R1) — se descarta, no se inventa
            food = await session.get(Food, uuid.UUID(food_id))
            if food is None:
                continue
            serving_size_g = float(food.serving_size_g) if food.serving_size_g else None
            grams = resolve_grams(item.get("approx_quantity_text", ""), serving_size_g)
            items_out.append(
                {
                    "food_id": food_id,
                    "name_es": food.name_es,
                    "grams": grams,
                    "approx_quantity_text": item.get("approx_quantity_text", ""),
                }
            )
    return items_out, agent_result
