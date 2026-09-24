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
from myfood.chat.conversations import active_conversation, create_conversation
from myfood.chat.flow import request_chat_message
from myfood.db.models import ChatConversation, ChatMessage
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
# Siempre un poco más que `CHAT_TURN_TIMEOUT_SECONDS`: así quien corta el turno es el worker
# (con su error concreto) y no esta espera, que solo sabría decir "tardó demasiado".
_WAIT_TIMEOUT_SECONDS = 60

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
    conversation_id: UUID | None = Form(default=None),
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

    ai_session = await request_chat_message(
        session, user_id, text=text, audio_bytes=audio_bytes, conversation_id=conversation_id
    )

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


class ChatConversationOut(BaseModel):
    id: UUID
    title: str | None
    created_at: str
    last_message_at: str


def _conversation_out(conversation: ChatConversation) -> ChatConversationOut:
    return ChatConversationOut(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at.isoformat(),
        last_message_at=conversation.last_message_at.isoformat(),
    )


@router.get("/conversations")
async def list_conversations(
    limit: int = 30,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> list[ChatConversationOut]:
    rows = await session.scalars(
        select(ChatConversation)
        .where(ChatConversation.user_id == user_id)
        .order_by(ChatConversation.last_message_at.desc())
        .limit(min(max(limit, 1), 100))
    )
    return [_conversation_out(c) for c in rows]


@router.post("/conversations", status_code=201)
async def create_new_conversation(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> ChatConversationOut:
    """Empieza un hilo nuevo sin borrar nada.

    La anterior sigue en la lista y se puede volver a ella. Se separa a propósito de
    `DELETE /history`, que sí borra: querer empezar de cero y querer que no quede rastro son
    dos cosas distintas (sección 7.9)."""
    return _conversation_out(await create_conversation(session, user_id))


@router.post("/reset", status_code=201)
async def start_new_conversation(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> ChatConversationOut:
    """Alias histórico de `POST /conversations`, que es como se llamaba cuando el corte se
    marcaba con un mensaje especial en vez de con una fila propia."""
    return _conversation_out(await create_conversation(session, user_id))


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> None:
    result = await session.execute(
        delete(ChatConversation).where(
            ChatConversation.id == conversation_id, ChatConversation.user_id == user_id
        )
    )
    if result.rowcount == 0:
        raise AppError("CONVERSATION_NOT_FOUND", "Esa conversación ya no existe.", status_code=404)
    await session.commit()


@router.get("/history")
async def get_chat_history(
    limit: int = 50,
    conversation_id: UUID | None = None,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> list[ChatHistoryItem]:
    """De más antiguo a más reciente, que es como se lee una conversación.

    El orden lo pone `seq` y no `created_at`: los dos mensajes de un turno se guardan con el
    mismo instante y ordenar por fecha sacaba la respuesta encima de la pregunta (migración
    0023). Cuando hay más mensajes que `limit` se recortan los MÁS ANTIGUOS, así que la
    consulta baja por `seq` y el resultado se le da la vuelta al final.
    """
    if conversation_id is None:
        conversation = await active_conversation(session, user_id)
        if conversation is None:
            return []
        conversation_id = conversation.id
    rows = await session.scalars(
        select(ChatMessage)
        .where(
            ChatMessage.user_id == user_id,
            ChatMessage.conversation_id == conversation_id,
        )
        .order_by(ChatMessage.seq.desc())
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
        for m in reversed(rows.all())
    ]


@router.delete("/history", status_code=204)
async def delete_chat_history(
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> None:
    """No toca `food_log` ni cambios ya aplicados (sección 7.9) — solo
    borra el propio historial de la conversación."""
    await session.execute(
        delete(ChatConversation).where(ChatConversation.user_id == user_id)
    )
    # Mensajes de antes de la migración 0023 no puede haber (se les asignó conversación), pero
    # borrar también por `user_id` deja la tabla limpia si algo quedase huérfano.
    await session.execute(delete(ChatMessage).where(ChatMessage.user_id == user_id))
    await session.commit()
