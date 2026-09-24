"""Hilos del chat (migración 0023).

Vive aparte de `chat/flow.py` porque lo necesitan las dos mitades de la regla 19: el proceso
`api` para listar y crear, y el `worker` para colgar de la conversación correcta los dos
mensajes del turno.

La conversación «activa» no se guarda en ninguna columna: es la de `last_message_at` más
reciente. Así no hay un estado que pueda quedar desincronizado, y crear una conversación nueva
es simplemente insertar una fila —que nace con `last_message_at = now()` y por tanto pasa a ser
la activa—, sin tener que desmarcar la anterior.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import ChatConversation
from myfood.errors import AppError

# Lo que se guarda como título: las primeras palabras del primer mensaje del usuario. Pedirle
# un título al modelo costaría una llamada por conversación para algo que solo sirve de
# etiqueta en una lista.
TITLE_MAX_CHARS = 60


def title_from_message(text: str) -> str:
    clean = " ".join(text.split())
    if len(clean) <= TITLE_MAX_CHARS:
        return clean
    return clean[: TITLE_MAX_CHARS - 1].rstrip() + "…"


async def create_conversation(session: AsyncSession, user_id: UUID) -> ChatConversation:
    conversation = ChatConversation(user_id=user_id)
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return conversation


async def active_conversation(
    session: AsyncSession, user_id: UUID
) -> ChatConversation | None:
    return await session.scalar(
        select(ChatConversation)
        .where(ChatConversation.user_id == user_id)
        .order_by(ChatConversation.last_message_at.desc())
        .limit(1)
    )


async def resolve_conversation(
    session: AsyncSession, user_id: UUID, conversation_id: UUID | None
) -> ChatConversation:
    """La conversación pedida, la activa, o una recién creada si el usuario no tiene ninguna.

    Se filtra siempre por `user_id` aunque la RLS ya lo haga (R3 + R11): un id de otro usuario
    debe comportarse como inexistente, no como un error distinto que delate que existe. Y si se
    pide una que no existe se devuelve 404 en vez de caer a la activa: mandar el mensaje a otro
    hilo en silencio es peor que fallar.
    """
    if conversation_id is not None:
        conversation = await session.scalar(
            select(ChatConversation).where(
                ChatConversation.id == conversation_id,
                ChatConversation.user_id == user_id,
            )
        )
        if conversation is None:
            raise AppError(
                "CONVERSATION_NOT_FOUND", "Esa conversación ya no existe.", status_code=404
            )
        return conversation
    return await active_conversation(session, user_id) or await create_conversation(
        session, user_id
    )
