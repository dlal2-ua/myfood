"""Escaneo OCR de tickets de compra (Fase 7) — ver `ai/flows/receipt_scan.py`."""

from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.ai.consent import require_ai_processing_consent
from myfood.ai.flows.receipt_scan import request_receipt_scan
from myfood.ai.quota import QuotaExceeded, check_and_consume_quota, reset_at_iso
from myfood.ai.schemas import AiSessionOut, ai_session_to_out
from myfood.deps import get_current_user_id, get_db
from myfood.errors import AppError

router = APIRouter(prefix="/receipts", tags=["receipts"])


@router.post("/scan", status_code=202)
async def scan_receipt(
    file: UploadFile = File(...),
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db),
) -> AiSessionOut:
    """No guarda nada todavía — el resultado (vía `GET /ai/sessions/{id}`,
    mismo patrón de polling que el resto de iafood) son candidatos de
    despensa editables; el usuario los revisa y confirma con `POST /pantry`
    normal."""
    await require_ai_processing_consent(session, user_id)
    try:
        await check_and_consume_quota(user_id, scope="receipt_scan")
    except QuotaExceeded as exc:
        raise AppError(
            exc.code, exc.message, status_code=429, details={"reset_at": reset_at_iso()}
        ) from exc

    image_bytes = await file.read()
    ai_session = await request_receipt_scan(
        session, user_id, image_bytes=image_bytes, content_type=file.content_type or ""
    )
    return ai_session_to_out(ai_session)
