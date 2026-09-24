"""Resolución de alimentos a partir de texto libre (RAG + function
calling), compartida por Smart Log (sección 10.8) y la importación de
recetas (sección 20: "cada línea de ingrediente... pasa por el mismo
resolutor que Smart Log"). Vive en su propio módulo para que ninguno de
los dos flujos dependa del otro.
"""

from __future__ import annotations

import uuid

from sqlalchemy import bindparam
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.ai import tools
from myfood.ai.agent import AgentResult, run_agent
from myfood.db.models import Food
from myfood.domain.food_candidates import EXCLUDE_RESTRICTED_SQL
from myfood.domain.food_mentions import split_into_food_mentions
from myfood.domain.quantity_text import compose_quantity_text, resolve_grams
from myfood.search import search_foods

# Alimentos por mención (ver `domain/food_mentions.py`) y tope total tras
# fusionar — una frase con muchas menciones no debe inflar sin límite el
# payload que se envía al LLM.
HITS_PER_MENTION = 10
GENERIC_HITS_PER_MENTION = 4
CANDIDATE_LIMIT = 40


async def search_candidates_for_text(text: str) -> list[dict]:
    """RAG: la frase completa casi nunca coincide con ningún alimento real
    en Meilisearch (comprobado contra el catálogo real — ver
    `domain/food_mentions.py`), así que se busca cada mención por separado
    y se fusionan los resultados, deduplicados por id.

    Dos consultas por mención, no una. El catálogo tiene 11.200 productos de marca de
    supermercado y por relevancia se comen los primeros puestos: «tortilla de patatas» devuelve
    cuatro marcas antes que el genérico de CIQUAL. Si el usuario dice que su tortilla es casera,
    el modelo necesita tener delante el genérico para poder elegirlo. La segunda consulta filtra
    a `kind = generic` y garantiza que siempre haya al menos un par.
    """
    seen: dict[str, dict] = {}
    for mention in split_into_food_mentions(text):
        hits, _total = await search_foods(mention, kind=None, limit=HITS_PER_MENTION, offset=0)
        generic_hits, _ = await search_foods(
            mention, kind="generic", limit=GENERIC_HITS_PER_MENTION, offset=0
        )
        # Los genéricos primero: si hay que recortar por `CANDIDATE_LIMIT`, que sobrevivan.
        for hit in [*generic_hits, *hits]:
            seen.setdefault(hit["id"], hit)
    return list(seen.values())[:CANDIDATE_LIMIT]


async def filter_restricted(
    session: AsyncSession, user_id: uuid.UUID, hits: list[dict]
) -> list[dict]:
    """Quita del RAG lo que el usuario no puede o no quiere comer.

    El chat ya lo hacía (`chat/tools.py`) y el registro por texto no: se le podían proponer
    alimentos con un alérgeno declarado y solo lo frenaba que el usuario lo viera al confirmar.
    """
    ids = [hit["id"] for hit in hits]
    if not ids:
        return []
    # Se buscan los PROHIBIDOS y se restan, en vez de quedarse con los permitidos: así esta
    # función solo hace lo suyo. Al revés, un id que Meilisearch tenga indexado pero ya no esté
    # en `foods` desaparecería aquí como si fuera una restricción del usuario, y de eso ya se
    # encarga `resolve_food_mentions`, que es donde se resuelve el alimento de verdad.
    stmt = sql_text(f"""
        SELECT f.id FROM foods f
        WHERE f.id IN :ids AND NOT ({EXCLUDE_RESTRICTED_SQL})
    """).bindparams(bindparam("ids", expanding=True))
    restricted = {
        str(row.id)
        for row in (await session.execute(stmt, {"ids": ids, "user_id": str(user_id)})).all()
    }
    return [hit for hit in hits if hit["id"] not in restricted]


_GENERIC_SOURCES = ("usda_foundation", "usda_sr", "ciqual", "bedca")


def build_candidates_payload(hits: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """Alias efímeros para los candidatos recuperados — mismo criterio que
    `ai/anonymize.py` para el plan de dieta, aunque aquí no hay datos
    personales que anonimizar (solo nombres de alimentos, dato de
    catálogo).

    Va más información por candidato que antes (marca, grupo, kcal/100 g, si es genérico) porque
    sin ella el modelo no podía distinguir un plato casero de uno envasado ni notar que estaba
    eligiendo un fiambre cuando le pedían pechuga. Solo campos que ya trae el documento de
    Meilisearch: añadir otros obligaría a reindexar el catálogo entero. Sigue sin salir ningún
    UUID (R5): solo alias.
    """
    alias_to_food_id: dict[str, str] = {}
    candidates_out = []
    for index, hit in enumerate(hits, start=1):
        alias = f"c{index}"
        alias_to_food_id[alias] = hit["id"]
        candidate: dict = {
            "id": alias,
            "name": hit["name_es"],
            "es_generico": hit.get("source") in _GENERIC_SOURCES,
        }
        if hit.get("food_group"):
            candidate["grupo"] = hit["food_group"]
        if hit.get("brand"):
            candidate["marca"] = hit["brand"]
        if hit.get("kcal_100g") is not None:
            candidate["kcal_100g"] = round(float(hit["kcal_100g"]))
        candidates_out.append(candidate)
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
) -> tuple[list[dict], AgentResult, dict]:
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
            grams = resolve_grams(
                compose_quantity_text(
                    item.get("approx_quantity_text", ""),
                    item.get("tipo_cantidad"),
                    item.get("tamano"),
                ),
                serving_size_g,
                food_name=food.name_es,
                category=food.category,
            )
            out = {
                "food_id": food_id,
                "name_es": food.name_es,
                "grams": grams,
                "approx_quantity_text": item.get("approx_quantity_text", ""),
            }
            # Lo que el modelo entendió, para que el usuario pueda juzgar la propuesta en vez
            # de aceptar un gramaje a ciegas. Solo se copian los campos que vengan.
            for field in ("tipo_cantidad", "tamano", "origen", "confianza", "motivo"):
                if item.get(field):
                    out[field] = item[field]
            alternativas = [
                alias_to_food_id[alias]
                for alias in (item.get("alternativas") or [])
                if alias in alias_to_food_id and alias_to_food_id[alias] != food_id
            ]
            if alternativas:
                out["alternativas"] = await _alternative_names(session, alternativas)
            items_out.append(out)
    extras = {
        "pregunta": (sink[-1].get("pregunta") or None) if sink else None,
        "no_encontrados": (sink[-1].get("no_encontrados") or []) if sink else [],
    }
    return items_out, agent_result, extras


async def _alternative_names(
    session: AsyncSession, food_ids: list[str]
) -> list[dict[str, str]]:
    """Los otros alimentos que el modelo consideró, con su nombre real: el usuario cambia de
    uno a otro con un toque en vez de volver a escribir la frase entera."""
    out = []
    for food_id in food_ids[:2]:
        food = await session.get(Food, uuid.UUID(food_id))
        if food is not None:
            out.append({"food_id": food_id, "name_es": food.name_es})
    return out
