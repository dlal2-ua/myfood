"""Escaneo OCR de tickets de compra → alta rápida en la despensa (Fase 7,
documento 1: "Escaneo de tickets de compra (OCR)"). Mismo patrón de dos
mitades (regla 19) que `recipe_import.py`: `request_receipt_scan` corre en
`api` (guarda la imagen ya procesada en el disco compartido con el worker,
crea la sesión, encola), `process_receipt_scan_job` corre en el `worker`
(OCR con Tesseract — `domain/receipt_ocr.py`, no es razonamiento, R2 — y
resolución línea a línea con el mismo resolutor de Smart Log/importación
de recetas).

El resultado (`response_payload["items"]`) son candidatos food_id + gramos
editables — el usuario los revisa y confirma cuáles añadir a la despensa
llamando a `POST /pantry` normal; nada se guarda solo (misma regla que el
resto de iafood)."""

from __future__ import annotations

import uuid
from io import BytesIO
from pathlib import Path
from uuid import UUID

from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.ai import client as ai_client
from myfood.ai.agent import AiAgentError
from myfood.ai.flows.food_resolution import (
    build_candidates_payload,
    resolve_food_mentions,
    search_candidates_for_text,
)
from myfood.ai.prompts import (
    RECEIPT_SCAN_PROMPT_VERSION,
    RECEIPT_SCAN_SYSTEM_V1,
    build_receipt_scan_line_prompt,
)
from myfood.ai.queue import enqueue_receipt_scan_job
from myfood.config import get_settings
from myfood.db.models import AiSession
from myfood.db.session import AdminSessionLocal
from myfood.domain.receipt_ocr import extract_lines
from myfood.errors import AppError

_AGENT_TIMEOUT_SECONDS = 20.0
_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_SUPPORTED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
# Subcarpeta de `image_storage_path` (sección 12) — mismo disco compartido
# entre `api` y `worker` que las imágenes de alimentos, no un directorio
# nuevo que montar aparte.
_RECEIPTS_DIR = Path(get_settings().image_storage_path) / "receipts"


async def request_receipt_scan(
    session: AsyncSession, user_id: UUID, *, image_bytes: bytes, content_type: str
) -> AiSession:
    """Corre en el proceso `api`. Determinista y local (validación +
    guardado de la imagen procesada); el OCR y la llamada al proveedor
    quedan para el worker (regla 19)."""
    credential_status = await ai_client.get_credential_status(session)
    if not credential_status.configured:
        raise AppError(
            "AI_NOT_CONFIGURED",
            "El administrador todavía no ha configurado la credencial de iafood.",
            status_code=503,
        )
    if len(image_bytes) > _MAX_IMAGE_BYTES:
        raise AppError("IMAGE_TOO_LARGE", "La imagen supera el tamaño máximo (8 MB).", 422)
    if content_type not in _SUPPORTED_CONTENT_TYPES:
        raise AppError("UNSUPPORTED_IMAGE_TYPE", "Formato de imagen no soportado.", 422)

    try:
        image = Image.open(BytesIO(image_bytes))
        image = image.convert("RGB")
    except Exception as exc:
        raise AppError("INVALID_IMAGE", "El archivo no es una imagen válida.", 422) from exc

    # Nunca se guarda el archivo subido tal cual (mismo criterio que el
    # resto de imágenes de usuario, sección 12): se reescala y se elimina
    # el EXIF (puede llevar geolocalización) reabriendo con Pillow y
    # reexportando en vez de copiar los bytes originales.
    image.thumbnail((2000, 2000))
    _RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    image_path = _RECEIPTS_DIR / f"{uuid.uuid4()}.jpg"
    image.save(image_path, format="JPEG", quality=85)

    ai_session = AiSession(
        user_id=user_id,
        kind="receipt_scan",
        status="running",
        request_payload={
            "prompt_version": RECEIPT_SCAN_PROMPT_VERSION,
            "image_path": str(image_path),
        },
    )
    session.add(ai_session)
    await session.commit()
    await session.refresh(ai_session)

    await enqueue_receipt_scan_job(str(ai_session.id))
    return ai_session


async def process_receipt_scan_job(ai_session_id: str) -> None:
    """Corre en el `worker` (regla 19)."""
    async with AdminSessionLocal() as session:
        ai_session = await session.get(AiSession, uuid.UUID(ai_session_id))
        if ai_session is None or ai_session.status != "running":
            return  # ya procesado, o no existe (defensivo)

        image_path = Path(ai_session.request_payload["image_path"])
        try:
            await _process(session, ai_session, image_path)
        finally:
            # La foto del ticket ya cumplió su función (extraer las
            # líneas); no hay motivo para conservarla — mismo criterio de
            # minimización de datos que el resto de la app.
            image_path.unlink(missing_ok=True)


async def _process(session: AsyncSession, ai_session: AiSession, image_path: Path) -> None:
    try:
        image_bytes = image_path.read_bytes()
    except OSError as exc:
        ai_session.status = "failed"
        ai_session.validation_errors = [{"code": "IMAGE_NOT_FOUND", "message": str(exc)}]
        await session.commit()
        return

    lines = extract_lines(image_bytes)
    if not lines:
        ai_session.status = "failed"
        ai_session.validation_errors = [
            {"code": "NO_TEXT_FOUND", "message": "No se ha reconocido texto en la imagen."}
        ]
        await session.commit()
        return

    token = await ai_client.get_decrypted_token(session)
    if token is None:
        ai_session.status = "failed"
        ai_session.validation_errors = [
            {"code": "AI_NOT_CONFIGURED", "message": "La credencial se retiró tras encolar."}
        ]
        await session.commit()
        return

    resolved_items: list[dict] = []
    total_input_tokens = 0
    total_output_tokens = 0

    for line in lines:
        hits = await search_candidates_for_text(line)
        if not hits:
            continue
        candidates_out, alias_to_food_id = build_candidates_payload(hits)

        try:
            items_out, agent_result, _extras = await resolve_food_mentions(
                session,
                token=token,
                prompt=build_receipt_scan_line_prompt(line, candidates_out),
                system_prompt=RECEIPT_SCAN_SYSTEM_V1,
                alias_to_food_id=alias_to_food_id,
                timeout_seconds=_AGENT_TIMEOUT_SECONDS,
            )
        except AiAgentError as exc:
            ai_session.status = "failed"
            ai_session.validation_errors = [{"code": exc.code, "message": str(exc)}]
            await session.commit()
            return

        total_input_tokens += agent_result.input_tokens
        total_output_tokens += agent_result.output_tokens
        for item in items_out:
            resolved_items.append({**item, "original_line": line})

    ai_session.status = "succeeded"
    ai_session.response_payload = {"items": resolved_items, "lines_found": len(lines)}
    ai_session.input_tokens = total_input_tokens
    ai_session.output_tokens = total_output_tokens
    await session.commit()
