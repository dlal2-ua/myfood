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
from myfood.errors import AppError

router = APIRouter(prefix="/consents", tags=["consents"])

# `health_data`: tratamiento de los datos de salud propios (peso, medidas, perfil...) —
# RGPD art. 9, obligatorio para usar la app (R4). `ai_processing`: enviar objetivos y
# restricciones anonimizados a Claude — opcional, solo para iafood.
KNOWN_CONSENTS: dict[str, bool] = {"health_data": True, "ai_processing": False}
REQUIRED_CONSENTS = tuple(kind for kind, required in KNOWN_CONSENTS.items() if required)
HEALTH_DATA_CONSENT = "health_data"


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


class ConsentStatusOut(BaseModel):
    kind: str
    required: bool
    granted: bool
    version: str | None
    granted_at: str | None
    revoked_at: str | None


@router.get("")
async def list_consents(
    user_id: UUID = Depends(get_current_user_id), session: AsyncSession = Depends(get_db)
) -> list[ConsentStatusOut]:
    rows = {
        c.kind: c
        for c in await session.scalars(select(Consent).where(Consent.user_id == user_id))
    }
    out = []
    for kind, required in KNOWN_CONSENTS.items():
        row = rows.get(kind)
        out.append(
            ConsentStatusOut(
                kind=kind,
                required=required,
                granted=row is not None and row.revoked_at is None,
                version=row.version if row else None,
                granted_at=row.granted_at.isoformat() if row else None,
                revoked_at=row.revoked_at.isoformat() if row and row.revoked_at else None,
            )
        )
    return out


@router.delete("/{kind}", status_code=204)
async def revoke_consent(
    kind: str,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> None:
    """Revocar es tan fácil como conceder (RGPD art. 7.3). Revocar `health_data`
    bloquea escribir perfil y medidas hasta volver a aceptar o borrar la cuenta
    (`POST /privacy/delete-account`); revocar `ai_processing` corta iafood."""
    row = await session.scalar(
        select(Consent).where(Consent.user_id == user_id, Consent.kind == kind)
    )
    if row is None or row.revoked_at is not None:
        raise AppError("CONSENT_NOT_GRANTED", "Ese consentimiento no está concedido.", 404)
    row.revoked_at = datetime.now(UTC)
    await session.commit()


async def require_health_data_consent(
    user_id: UUID = Depends(get_current_user_id), session: AsyncSession = Depends(get_db)
) -> None:
    """Dependencia de los endpoints que escriben datos de salud cifrados (R4)."""
    granted = await session.scalar(
        select(Consent.id).where(
            Consent.user_id == user_id,
            Consent.kind == HEALTH_DATA_CONSENT,
            Consent.revoked_at.is_(None),
        )
    )
    if granted is None:
        raise AppError(
            "HEALTH_DATA_CONSENT_REQUIRED",
            "Debes aceptar el tratamiento de tus datos de salud antes de guardarlos.",
            status_code=403,
        )
