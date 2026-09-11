"""Suscripción a Web Push (sección 10, Fase 3) — VAPID autoalojado, sin
Firebase ni terceros. El envío en sí vive en `myfood/push.py` y se dispara
desde el worker (`myfood/worker.py`) según `notification_rules`.
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.config import get_settings
from myfood.db.models import PushSubscription
from myfood.deps import get_current_user_id, get_db

router = APIRouter(prefix="/push", tags=["push"])
settings = get_settings()


@router.get("/vapid-public-key")
async def vapid_public_key() -> dict:
    return {"public_key": settings.vapid_public_key}


class SubscribeKeys(BaseModel):
    p256dh: str
    auth: str


class SubscribeIn(BaseModel):
    endpoint: str
    keys: SubscribeKeys
    device: str | None = None


@router.post("/subscribe", status_code=201)
async def subscribe(
    body: SubscribeIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Guarda o actualiza la suscripción del navegador actual. Caso conocido
    sin cubrir (documentado, no bloqueante para un uso personal/familiar
    típico): si el mismo navegador ya estaba suscrito con OTRA cuenta antes
    de cerrar sesión, `endpoint` (único a nivel de fila) colisiona con esa
    fila ajena, invisible bajo RLS para el usuario actual — el INSERT
    devolvería un 500 en vez de reasignar la suscripción. No se ha
    encontrado necesario resolverlo para el caso de uso previsto (cada
    persona con su propio dispositivo)."""
    existing = await session.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)
    )
    if existing is not None:
        existing.p256dh = body.keys.p256dh
        existing.auth = body.keys.auth
        existing.device = body.device
        await session.commit()
        return {"id": str(existing.id)}

    sub = PushSubscription(
        user_id=user_id,
        endpoint=body.endpoint,
        p256dh=body.keys.p256dh,
        auth=body.keys.auth,
        device=body.device,
    )
    session.add(sub)
    await session.commit()
    await session.refresh(sub)
    return {"id": str(sub.id)}


class UnsubscribeIn(BaseModel):
    endpoint: str


@router.post("/unsubscribe", status_code=204)
async def unsubscribe(
    body: UnsubscribeIn,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> None:
    sub = await session.scalar(
        select(PushSubscription).where(
            PushSubscription.endpoint == body.endpoint, PushSubscription.user_id == user_id
        )
    )
    if sub is not None:
        await session.delete(sub)
        await session.commit()
