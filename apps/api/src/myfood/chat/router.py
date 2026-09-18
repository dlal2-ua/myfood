"""Chat conversacional (sección 7.9/24). `POST /chat/message` es la única
ruta de iafood que responde de forma síncrona en vez de 202+polling — ver
`chat/flow.py` para por qué eso no rompe la regla 19."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.ai.consent import require_ai_processing_consent
from myfood.ai.limits import load_limits
from myfood.ai.queue import wait_for_chat_result
from myfood.ai.quota import QuotaExceeded, check_and_consume_quota, reset_at_iso
from myfood.chat.flow import request_chat_message
from myfood.db.models import ChatMessage
from myfood.deps import get_current_user_id, get_db
from myfood.errors import AppError

router = APIRouter(prefix="/chat", tags=["chat"])

_ALLOWED_AUDIO_CONTENT_TYPES = {
    "audio/ogg",
    "audio/webm",
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/mp4",
    "audio/m4a",
    "audio/aac",
}
_MAX_AUDIO_BYTES = 15 * 1024 * 1024
# Turno del chat (sección 24.5) + un margen breve para el propio Redis
# BRPOP — evita que el 504 llegue justo antes de que el worker termine.
_WAIT_TIMEOUT_SECONDS = 22

_WORKER_ERROR_MESSAGES = {
    "AI_NOT_CONFIGURED": "El administrador todavía no ha configurado la credencial de iafood.",
    "AI_CREDENTIAL_INVALID": (
        "La credencial de iafood no es válida — el administrador debe renovarla."
    ),
    "AI_TIMEOUT": "El proveedor de IA ha tardado demasiado. Inténtalo de nuevo.",
    "TRANSCRIPTION_UNAVAILABLE": (
        "No se pudo transcribir la nota de voz. Puedes escribir tu mensaje en su lugar."
    ),
}


class ChatProposalOut(BaseModel):
    scope: str
    ai_proposal_id: UUID
    payload: dict


class ChatMessageOut(BaseModel):
    message: str
    proposal: ChatProposalOut | None = None


@router.post("/message")
async def send_chat_message(
    text: str | None = Form(default=None),
    audio: UploadFile | None = File(default=None),
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> ChatMessageOut:
    await require_ai_processing_consent(session, user_id)

    audio_bytes: bytes | None = None
    if audio is not None:
        if audio.content_type not in _ALLOWED_AUDIO_CONTENT_TYPES:
            raise AppError(
                "UNSUPPORTED_AUDIO_TYPE", "Formato de audio no soportado.", status_code=422
            )
        audio_bytes = await audio.read()
        if len(audio_bytes) > _MAX_AUDIO_BYTES:
            raise AppError(
                "AUDIO_TOO_LARGE", "La nota de voz es demasiado larga.", status_code=422
            )

    limits = load_limits()
    try:
        await check_and_consume_quota(
            user_id,
            scope="chat",
            per_profile_limit=limits.chat_messages_per_profile_daily,
            enforce_instance=False,
        )
    except QuotaExceeded as exc:
        raise AppError(
            exc.code, exc.message, status_code=429, details={"reset_at": reset_at_iso()}
        ) from exc

    ai_session = await request_chat_message(session, user_id, text=text, audio_bytes=audio_bytes)

    result = await wait_for_chat_result(str(ai_session.id), timeout_seconds=_WAIT_TIMEOUT_SECONDS)
    if result is None:
        raise AppError(
            "CHAT_TIMEOUT",
            "La respuesta está tardando demasiado. Tu mensaje ya está guardado, puedes "
            "consultar el historial o volver a intentarlo.",
            status_code=504,
        )
    if "error" in result:
        error_code = result["error"]
        # 503 y no 502: Cloudflare sustituye el cuerpo de cualquier 502/504
        # del origen por su propia página (encontrado en vivo: el cliente
        # veía "error code: 502" en vez del JSON con el código real), y
        # todos estos son fallos de un servicio del que depende el chat.
        raise AppError(
            error_code,
            _WORKER_ERROR_MESSAGES.get(error_code, "No se pudo procesar el mensaje."),
            status_code=503,
        )

    proposal = None
    raw_proposal = result.get("proposal")
    if raw_proposal:
        proposal = ChatProposalOut(
            scope=raw_proposal["scope"],
            ai_proposal_id=UUID(raw_proposal["ai_proposal_id"]),
            payload=raw_proposal["payload"],
        )
    return ChatMessageOut(message=result["message"], proposal=proposal)


class ChatHistoryItem(BaseModel):
    id: UUID
    role: str
    content: str
    source: str
    created_at: str


@router.get("/history")
async def get_chat_history(
    limit: int = 50,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> list[ChatHistoryItem]:
    rows = await session.scalars(
        select(ChatMessage)
        .where(ChatMessage.user_id == user_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(min(max(limit, 1), 200))
    )
    return [
        ChatHistoryItem(
            id=m.id,
            role=m.role,
            content=m.content,
            source=m.source,
            created_at=m.created_at.isoformat(),
        )
        for m in rows
    ]


@router.delete("/history", status_code=204)
async def delete_chat_history(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> None:
    """No toca `food_log` ni cambios ya aplicados (sección 7.9) — solo
    borra el propio historial de la conversación."""
    await session.execute(delete(ChatMessage).where(ChatMessage.user_id == user_id))
    await session.commit()
