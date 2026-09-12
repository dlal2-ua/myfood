"""Comprobación del consentimiento `ai_processing` (R4/RGPD art. 9),
compartida por cualquier endpoint que dispare un flujo de iafood — no solo
la generación de dietas, también Smart Log y lo que venga después."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import Consent
from myfood.errors import AppError

AI_PROCESSING_CONSENT_KIND = "ai_processing"


async def require_ai_processing_consent(session: AsyncSession, user_id: UUID) -> None:
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
