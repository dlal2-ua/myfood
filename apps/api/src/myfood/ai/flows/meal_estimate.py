"""Lo que comparten el registro por texto y el registro por foto: pedirle al modelo que
estime lo que se ha comido, plato a plato, y dejarlo como una propuesta de diario.

Los dos acaban igual porque son la misma pregunta con distinta entrada —una frase o una
imagen—: el modelo devuelve cada plato entero con su desglose (`estimate_meal`),
`domain/diary_proposal.py` lo afina contra el catálogo y lo acota, y el usuario lo aprueba o
lo rechaza entero con la misma tarjeta que en el chat.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from myfood.ai import tools
from myfood.ai.agent import AgentResult, run_agent
from myfood.db.models import AiProposal, AiSession
from myfood.domain import diary_proposal

# 4 y no 1: el CLI corta con «Reached maximum number of turns» si el modelo gasta un turno
# antes de llamar a la herramienta. Subir el techo no cuesta tokens.
_MAX_TURNS = 4


async def estimate_meal(
    *,
    token: str,
    prompt: str,
    system_prompt: str,
    timeout_seconds: float,
    images: list[tuple[str, str]] | None = None,
) -> tuple[dict, AgentResult]:
    """La llamada al modelo: de un texto o una foto a los platos estimados. Devuelve lo que
    el modelo mandó a `estimate_meal` (vacío si no la llamó). Puede lanzar `AiAgentError`."""
    sink: list[dict] = []
    result = await run_agent(
        token=token,
        prompt=prompt,
        system_prompt=system_prompt,
        mcp_tools=[tools.build_estimate_meal_tool(sink)],
        max_turns=_MAX_TURNS,
        timeout_seconds=timeout_seconds,
        images=images,
    )
    return (sink[-1] if sink else {}), result


async def store_proposal(session: AsyncSession, ai_session: AiSession, args: dict) -> dict:
    """Construye la propuesta de diario y la deja pendiente. Lanza `AppError` si lo estimado
    no se puede apuntar (valores imposibles, nada reconocible)."""
    requested_day = date.fromisoformat(args["date"])
    payload = await diary_proposal.build_payload(
        session,
        args,
        alias_to_candidate={},
        # Aquí la fecha no la deduce nadie: es el día que el usuario tiene abierto en el
        # diario, que también puede apuntar a mano en una fecha futura.
        today=max(date.today(), requested_day),
    )
    proposal = AiProposal(
        ai_session_id=ai_session.id,
        user_id=ai_session.user_id,
        scope="diary",
        payload=payload,
        rationale=None,
        status="pending",
    )
    session.add(proposal)
    await session.flush()
    return {"ai_proposal_id": str(proposal.id), "payload": payload}


def response_payload(
    proposal: dict | None,
    *,
    question: str | None,
    from_saved: bool = False,
    empty_warning: str = "NO_MATCH",
) -> dict:
    return {
        "proposal": proposal,
        # Una sola pregunta del modelo cuando algo que cambia mucho el resultado está de
        # verdad ambiguo. La propuesta se manda igual: el usuario la ve mientras decide.
        "pregunta": question,
        # Todo salió de platos ya guardados: no se ha llamado al modelo.
        "from_saved": from_saved,
        # Vacío siempre. Es el formato de antes (alimentos del catálogo a confirmar uno a
        # uno): se conserva la clave para que una web en caché no falle al leerla.
        "items": [],
        "warning": None if proposal else empty_warning,
    }
