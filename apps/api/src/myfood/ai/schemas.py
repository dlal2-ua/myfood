"""Forma de salida compartida para el estado de una `ai_session` (sección
7.7) — la misma para cualquier `kind` (plan de dieta, Smart Log...), así
`GET /ai/sessions/{id}` sirve para todas sin cambios, y cada router que
encola un tipo de sesión (`routers/ai.py`, `routers/log.py`) devuelve la
misma forma nada más crearla."""

from uuid import UUID

from pydantic import BaseModel

from myfood.db.models import AiSession


class AiSessionOut(BaseModel):
    id: UUID
    kind: str
    status: str
    attempts: int
    response_payload: dict | None
    validation_errors: list | None


def ai_session_to_out(ai_session: AiSession) -> AiSessionOut:
    return AiSessionOut(
        id=ai_session.id,
        kind=ai_session.kind,
        status=ai_session.status,
        attempts=ai_session.attempts,
        response_payload=ai_session.response_payload,
        validation_errors=ai_session.validation_errors,
    )
