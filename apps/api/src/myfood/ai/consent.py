"""Puerta de entrada a iafood, compartida por cualquier endpoint que dispare un flujo — no
solo la generación de dietas, también Smart Log, el chat y lo que venga después.

Comprueba dos cosas distintas que van siempre juntas:
- el consentimiento `ai_processing` del usuario (R4/RGPD art. 9), que da él;
- que el administrador le haya habilitado la IA (`users.ai_enabled`, migración 0019), que es
  quien paga la cuota de Claude.

Las dos viven aquí a propósito: es el único sitio por el que pasan todos los flujos, así que
añadir uno nuevo no puede saltarse ninguna de las dos por olvido."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import Consent, User
from myfood.errors import AppError

AI_PROCESSING_CONSENT_KIND = "ai_processing"


async def require_ai_processing_consent(session: AsyncSession, user_id: UUID) -> None:
    user = await session.get(User, user_id)
    if user is not None and not user.ai_enabled:
        raise AppError(
            "AI_DISABLED_FOR_USER",
            "El administrador no ha habilitado las funciones con IA para tu cuenta.",
            status_code=403,
        )

    consent = await session.scalar(
        select(Consent).where(
            Consent.user_id == user_id,
            Consent.kind == AI_PROCESSING_CONSENT_KIND,
            Consent.revoked_at.is_(None),
        )
    )
    if consent is None:
        raise AppError(
            "AI_CONSENT_REQUIRED",
            "Debes aceptar el consentimiento de procesamiento con IA "
            "(POST /consents con kind='ai_processing') antes de usar iafood.",
            status_code=403,
        )
