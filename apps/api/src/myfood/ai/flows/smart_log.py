"""Registro por lenguaje natural desde el Diario, "Smart Log" (sección 10.8).

Hace lo mismo que el chat cuando se le cuenta lo que se ha comido, y con las mismas reglas
(`ai/prompts.py::MEAL_ESTIMATE_RULES`): cada plato se estima ENTERO con el conocimiento general
del modelo, con su desglose al lado, en vez de despiezarlo contra el catálogo. El catálogo
dejó de ser el punto de partida porque «un bocadillo de pan de cristal con pastrami» acababa
convertido en cinco alimentos sueltos que no eran lo que se había comido. Tampoco hay búsqueda
web: el modelo ya sabe lo que lleva un plato corriente y los resultados de una búsqueda
multiplican los tokens de cada registro.

Tres caminos, del más barato al más caro:
1. `resolve_saved_dishes` (proceso `api`, sin modelo, sin cuota): todo lo que dice la frase
   son platos que el usuario ya guardó en el catálogo. La respuesta es inmediata.
2. `request_smart_log` (proceso `api`) encola, y
3. `process_smart_log_job` (`worker`, regla 19: el único que llama al Agent SDK) estima.

El resultado NUNCA se guarda solo: queda una propuesta de diario (`ai_proposals`,
scope='diary') que el usuario ve con su total y su desglose, y aprueba o rechaza entera con
`POST /ai/proposals/{id}/approve` — la misma tarjeta y el mismo camino que en el chat.
"""

from __future__ import annotations

import uuid
from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from myfood.ai import client as ai_client
from myfood.ai.agent import AiAgentError
from myfood.ai.flows.meal_estimate import estimate_meal, response_payload, store_proposal
from myfood.ai.prompts import (
    SMART_LOG_PROMPT_VERSION,
    SMART_LOG_SYSTEM_V3,
    build_meal_estimate_prompt,
)
from myfood.ai.queue import enqueue_smart_log_job
from myfood.db.models import AiSession
from myfood.db.session import AdminSessionLocal
from myfood.domain import estimated_dishes
from myfood.errors import AppError

# El subproceso del CLI tarda unos segundos solo en arrancar, y aquí el modelo escribe más
# que antes: cada plato lleva sus cifras y su desglose, no solo un alias.
_AGENT_TIMEOUT_SECONDS = 45.0


async def resolve_saved_dishes(
    session: AsyncSession, user_id: UUID, *, text: str, log_date: str, meal_type: str
) -> AiSession | None:
    """Si TODO lo que dice el texto son platos ya guardados, deja la propuesta hecha sin
    llamar al modelo y devuelve una sesión ya terminada; si no, `None`.

    Es la mitad del motivo de guardar un plato: la segunda «marinera» no gasta tokens, no
    gasta cuota y no espera a nadie."""
    saved = await estimated_dishes.load_saved(session)
    resolved = estimated_dishes.resolve_without_model(text, saved)
    if resolved is None:
        return None

    ai_session = AiSession(
        user_id=user_id,
        kind="smart_log",
        status="succeeded",
        request_payload={"text": text, "log_date": log_date, "meal_type": meal_type},
        input_tokens=0,
        output_tokens=0,
    )
    session.add(ai_session)
    await session.flush()
    try:
        proposal = await store_proposal(
            session,
            ai_session,
            {
                "date": log_date,
                "meal_type": estimated_dishes.detect_meal_type(text) or meal_type,
                "request": text,
                "items": [{"nombre": dish.name, "cantidad": count} for count, dish in resolved],
            },
        )
    except AppError:
        # «20 marineras»: que lo mire el modelo, que al menos puede preguntar.
        await session.rollback()
        return None
    ai_session.response_payload = response_payload(proposal, question=None, from_saved=True)
    await session.commit()
    await session.refresh(ai_session)
    return ai_session


async def request_smart_log(
    session: AsyncSession, user_id: UUID, *, text: str, log_date: str, meal_type: str
) -> AiSession:
    """Corre en el proceso `api`: crea la sesión y encola. La llamada al proveedor queda para
    el worker (regla 19)."""
    credential_status = await ai_client.get_credential_status(session)
    if not credential_status.configured:
        raise AppError(
            "AI_NOT_CONFIGURED",
            "El administrador todavía no ha configurado la credencial de iafood.",
            status_code=503,
        )

    ai_session = AiSession(
        user_id=user_id,
        kind="smart_log",
        status="running",
        request_payload={
            "prompt_version": SMART_LOG_PROMPT_VERSION,
            "text": text,
            "log_date": log_date,
            "meal_type": meal_type,
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

        token = await ai_client.get_decrypted_token(session)
        if token is None:
            ai_session.status = "failed"
            ai_session.validation_errors = [
                {"code": "AI_NOT_CONFIGURED", "message": "La credencial se retiró tras encolar."}
            ]
            await session.commit()
            return

        saved = await estimated_dishes.load_saved(session)
        known = [dish.name for dish in estimated_dishes.mentioned(text, saved)]
        try:
            args, agent_result = await estimate_meal(
                token=token,
                prompt=build_meal_estimate_prompt(text, known),
                system_prompt=SMART_LOG_SYSTEM_V3,
                timeout_seconds=_AGENT_TIMEOUT_SECONDS,
            )
        except AiAgentError as exc:
            ai_session.status = "failed"
            ai_session.validation_errors = [{"code": exc.code, "message": str(exc)}]
            await session.commit()
            return

        ai_session.input_tokens = agent_result.input_tokens
        ai_session.output_tokens = agent_result.output_tokens
        question = str(args.get("pregunta") or "").strip() or None
        dishes = [d for d in args.get("platos") or [] if isinstance(d, dict)]

        proposal: dict | None = None
        if dishes:
            try:
                proposal = await store_proposal(
                    session,
                    ai_session,
                    {
                        "date": request_payload.get("log_date") or date.today().isoformat(),
                        "meal_type": request_payload.get("meal_type") or "lunch",
                        "request": text,
                        "items": dishes,
                    },
                )
            except AppError as exc:
                # Un mensaje honesto de por qué no se puede, en vez de apuntar algo dudoso.
                ai_session.status = "failed"
                ai_session.validation_errors = [{"code": exc.code, "message": exc.message}]
                await session.commit()
                return

        ai_session.status = "succeeded"
        ai_session.response_payload = response_payload(proposal, question=question)
        await session.commit()
