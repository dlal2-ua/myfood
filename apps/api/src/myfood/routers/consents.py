"""Consentimientos RGPD art. 9 (R4/sección 7.1). Endpoint pendiente desde la
Fase 0 — `Consent` ya existía como modelo y `/auth/me` ya devolvía
`granted_consents`, pero no había ninguna forma de conceder uno todavía.
Bloqueaba en la práctica el consentimiento `ai_processing` que exige
`POST /ai/diet-plan` (sección 10.6) antes de enviar nada a la IA.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.db.models import Consent
from myfood.deps import get_current_user_id, get_db

router = APIRouter(prefix="/consents", tags=["consents"])


class ConsentIn(BaseModel):
    kind: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=50)


class ConsentOut(BaseModel):
    kind: str
    version: str
    granted_at: str


@router.post("", status_code=201)
async def grant_consent(
    body: ConsentIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> ConsentOut:
    """Idempotente por `kind`: conceder de nuevo (misma versión u otra)
    reactiva el consentimiento si estaba revocado, en vez de acumular filas
    duplicadas — el historial de versiones no es un requisito de esta fase."""
    existing = await session.scalar(
        select(Consent).where(Consent.user_id == user_id, Consent.kind == body.kind)
    )
    if existing is not None:
        existing.version = body.version
        existing.revoked_at = None
        # `server_default` solo dispara en el INSERT original — sin esto,
        # reconceder un consentimiento revocado dejaría `granted_at` con la
        # fecha de la concesión antigua en vez de la de esta reactivación.
        existing.granted_at = datetime.now(UTC)
        consent = existing
    else:
        consent = Consent(user_id=user_id, kind=body.kind, version=body.version)
        session.add(consent)
    await session.commit()
    await session.refresh(consent)
    return ConsentOut(
        kind=consent.kind, version=consent.version, granted_at=consent.granted_at.isoformat()
    )
