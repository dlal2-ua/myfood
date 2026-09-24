"""Respaldo por búsqueda web: qué hacer con lo que no está en el catálogo.

Solo se dispara cuando la resolución contra el catálogo se queda sin nada para algo que el
usuario ha mencionado, y solo si el administrador lo tiene activado (`web_search_fallback` en
`data/config/iafood.json`). Es deliberadamente un segundo turno aparte, no una herramienta más
del turno principal: así solo paga el coste de la búsqueda la minoría de peticiones que lo
necesita, en vez de todas.

Lo que sale de aquí NUNCA entra en `foods` (R9). No viene del ETL, así que no puede acabar en
el catálogo como si fuera un dato de fuente oficial: se queda en una propuesta de diario con
`entry_source='ai_estimate'` y con la URL de donde salió el número, visible para el usuario.
"""

from __future__ import annotations

import logging
from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from myfood.ai import tools
from myfood.ai.agent import AgentResult, AiAgentError, run_agent
from myfood.ai.limits import load_limits
from myfood.ai.prompts import WEB_ESTIMATE_SYSTEM_V1, build_web_estimate_prompt
from myfood.db.models import AiProposal, AiSession
from myfood.domain import diary_proposal
from myfood.domain.quantity_text import compose_quantity_text, resolve_grams
from myfood.errors import AppError

logger = logging.getLogger("myfood.ai.web_estimate")

# Una búsqueda que lee un par de páginas ronda los 20 s medidos en vivo, pero depende de
# lo que tarde la web de turno. Con 40 s se quedaba corto de vez en cuando y el respaldo
# fallaba en silencio.
_TIMEOUT_SECONDS = 70.0
# Suficiente para buscar, leer un par de resultados y contestar. Más vueltas serían más coste
# por un alimento que, para empezar, es el que menos falta hace clavar.
_MAX_TURNS = 4
# La herramienta del CLI de Claude Code, no la de la API: va incluida en la suscripción, así
# que lo que cuesta de verdad son los tokens de los resultados, no la búsqueda en sí.
WEB_SEARCH_TOOL = "WebSearch"


def is_enabled() -> bool:
    return load_limits().web_search_fallback


async def estimate_missing_foods(
    session: AsyncSession,
    *,
    token: str,
    user_id: UUID,
    ai_session: AiSession,
    missing: list[str],
    log_date: str,
    meal_type: str,
) -> tuple[dict | None, AgentResult | None]:
    """Busca en internet lo que el catálogo no tenía y deja una propuesta de diario.

    Devuelve `(propuesta, resultado)` o `(None, resultado)` si no ha sacado nada en claro. No
    lanza: que falle el respaldo no puede tumbar el registro, que ya tiene sus otros alimentos
    resueltos contra el catálogo.
    """
    if not missing or not is_enabled():
        return None, None

    sink: list[dict] = []
    try:
        result = await run_agent(
            token=token,
            prompt=build_web_estimate_prompt(missing),
            system_prompt=WEB_ESTIMATE_SYSTEM_V1,
            mcp_tools=[tools.build_estimate_foods_tool(sink)],
            extra_tools=[WEB_SEARCH_TOOL],
            max_turns=_MAX_TURNS,
            timeout_seconds=_TIMEOUT_SECONDS,
        )
    except AiAgentError as exc:
        # Que falle el respaldo no puede tumbar el registro, pero tampoco puede no dejar
        # rastro: sin esta línea, una búsqueda que se cae es indistinguible de una que
        # simplemente no encontró nada, y no hay por dónde empezar a mirar.
        logger.warning("el respaldo web falló (%s): %s", exc.code, exc)
        return None, None

    raw_items = sink[-1].get("items", []) if sink else []
    entries = []
    for item in raw_items:
        nombre = str(item.get("nombre") or "").strip()
        if not nombre:
            continue
        grams = resolve_grams(
            compose_quantity_text(
                str(item.get("cantidad_texto") or ""), item.get("tipo_cantidad"), item.get("tamano")
            ),
            None,
            food_name=nombre,
        )
        entries.append(
            {
                "name": nombre,
                "grams": grams,
                "kcal_100g": item.get("kcal_100g"),
                "protein_100g": item.get("protein_100g"),
                "fat_100g": item.get("fat_100g"),
                "carbs_100g": item.get("carbs_100g"),
                "source_url": str(item.get("fuente") or "").strip() or None,
            }
        )
    if not entries:
        return None, result

    try:
        payload = await diary_proposal.build_payload(
            session,
            {"date": log_date, "meal_type": meal_type, "items": entries,
             "request": "Lo que no estaba en el catálogo"},
            alias_to_candidate={},
            today=date.today(),
        )
    except AppError as exc:
        # Valores no plausibles (`IMPLAUSIBLE_ESTIMATE`) o fecha mala: mejor no proponer nada
        # que meter un número imposible en el histórico.
        logger.warning("el respaldo web devolvió algo que no se puede apuntar: %s", exc.code)
        return None, result

    proposal = AiProposal(
        ai_session_id=ai_session.id,
        user_id=user_id,
        scope="diary",
        payload=payload,
        rationale=None,
        status="pending",
    )
    session.add(proposal)
    await session.flush()
    return {"ai_proposal_id": str(proposal.id), "payload": payload}, result
