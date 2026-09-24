"""Flujo de registro por lenguaje natural, "Smart Log" (sección 10.8).

Mismo patrón de dos mitades que `ai/flows/diet_plan.py` (regla 19):
`request_smart_log` corre en el proceso `api` (RAG vía Meilisearch, encola
el trabajo) y `process_smart_log_job` corre en el `worker` (la única que
llama al Agent SDK, vía `ai/flows/food_resolution.py` — compartida con la
importación de recetas). El resultado NUNCA se guarda solo —
`response_payload` son alimentos propuestos que el usuario revisa, ajusta
gramos y confirma llamando a `POST /log/food` normal por cada uno (sección
10.8: "responde 200 con la lista de items propuestos, SIN guardar nada
todavía" — aquí, como en el resto de iafood, la respuesta llega vía
`ai_sessions`/polling en vez de en la propia petición, por la regla 19).
"""

from __future__ import annotations

import uuid
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from myfood.ai import client as ai_client
from myfood.ai.agent import AiAgentError
from myfood.ai.flows.food_resolution import (
    build_candidates_payload,
    filter_restricted,
    resolve_food_mentions,
    search_candidates_for_text,
)
from myfood.ai.prompts import (
    SMART_LOG_PROMPT_VERSION,
    SMART_LOG_SYSTEM_V2,
    build_smart_log_user_prompt,
)
from myfood.ai.queue import enqueue_smart_log_job
from myfood.db.models import AiSession
from myfood.db.session import AdminSessionLocal
from myfood.errors import AppError

_AGENT_TIMEOUT_SECONDS = 30.0


async def request_smart_log(session: AsyncSession, user_id: UUID, *, text: str) -> AiSession:
    """Corre en el proceso `api`. El RAG (Meilisearch) y la creación de la
    sesión son deterministas y locales; la llamada real al proveedor queda
    para el worker (regla 19)."""
    credential_status = await ai_client.get_credential_status(session)
    if not credential_status.configured:
        raise AppError(
            "AI_NOT_CONFIGURED",
            "El administrador todavía no ha configurado la credencial de iafood.",
            status_code=503,
        )

    hits = await search_candidates_for_text(text)
    # Lo que el usuario no puede comer no entra siquiera como candidato (R4): el chat ya lo
    # filtraba y este flujo no, así que se le podían proponer alimentos con un alérgeno suyo.
    hits = await filter_restricted(session, user_id, hits)
    if not hits:
        raise AppError(
            "NO_CANDIDATE_FOODS",
            "No se ha encontrado ningún alimento parecido en el catálogo para ese texto.",
            status_code=422,
        )
    candidates_out, alias_to_food_id = build_candidates_payload(hits)

    ai_session = AiSession(
        user_id=user_id,
        kind="smart_log",
        status="running",
        request_payload={
            "prompt_version": SMART_LOG_PROMPT_VERSION,
            "text": text,
            "candidates": candidates_out,
            "alias_to_food_id": alias_to_food_id,
        },
    )
    session.add(ai_session)
    await session.commit()
    await session.refresh(ai_session)

    await enqueue_smart_log_job(str(ai_session.id))
    return ai_session


async def process_smart_log_job(ai_session_id: str) -> None:
    """Corre en el `worker` (regla 19)."""
    async with AdminSessionLocal() as session:
        ai_session = await session.get(AiSession, uuid.UUID(ai_session_id))
        if ai_session is None or ai_session.status != "running":
            return  # ya procesado, o no existe (defensivo)

        request_payload = ai_session.request_payload
        text: str = request_payload["text"]
        candidates: list[dict] = request_payload["candidates"]
        alias_to_food_id: dict[str, str] = request_payload["alias_to_food_id"]

        token = await ai_client.get_decrypted_token(session)
        if token is None:
            ai_session.status = "failed"
            ai_session.validation_errors = [
                {"code": "AI_NOT_CONFIGURED", "message": "La credencial se retiró tras encolar."}
            ]
            await session.commit()
            return

        try:
            items_out, agent_result, extras = await resolve_food_mentions(
                session,
                token=token,
                prompt=build_smart_log_user_prompt(text, candidates),
                system_prompt=SMART_LOG_SYSTEM_V2,
                alias_to_food_id=alias_to_food_id,
                timeout_seconds=_AGENT_TIMEOUT_SECONDS,
            )
        except AiAgentError as exc:
            ai_session.status = "failed"
            ai_session.validation_errors = [{"code": exc.code, "message": str(exc)}]
            await session.commit()
            return

        ai_session.status = "succeeded"
        ai_session.response_payload = {
            "items": items_out,
            "warning": None if items_out else "NO_MATCH",
            # Una sola pregunta del modelo cuando algo que cambia mucho el gramaje está de
            # verdad ambiguo. La propuesta se manda igual: el usuario la ve mientras decide.
            "pregunta": extras["pregunta"],
            # Lo que se mencionó y no existe en el catálogo. Antes se descartaba en silencio
            # (`food_resolution` hacía `continue`) y el día salía con menos calorías de las
            # que se habían comido, sin ninguna pista de por qué.
            "no_encontrados": extras["no_encontrados"],
        }
        ai_session.input_tokens = agent_result.input_tokens
        ai_session.output_tokens = agent_result.output_tokens
        await session.commit()
