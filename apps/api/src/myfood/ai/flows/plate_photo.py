"""Registro por foto del plato.

Es la primera vez que el modelo ve algo que no es texto. La única foto que entraba hasta ahora
en un flujo de iafood era el ticket de la compra, y ni siquiera le llegaba: se pasaba por
Tesseract en local (`domain/receipt_ocr.py`, R2) y a Claude solo le llegaban las líneas.

Dos fases, porque R1 no se relaja por ser una imagen:

1. VISIÓN. Claude mira la foto y describe lo que ve — nombre del alimento, si le parece casero
   o de paquete, en qué unidad está contada la cantidad y cuántas, si la ración es grande o
   pequeña, y qué ha usado de referencia para el tamaño. **Ni gramos ni calorías.**
2. CATÁLOGO. Lo que ha visto pasa por el MISMO resolutor que el registro por texto
   (`ai/flows/food_resolution.py`): se buscan candidatos reales, se filtran las restricciones
   del usuario, el modelo elige entre ellos y `domain/quantity_text.py` pone los gramos. Las
   calorías salen del dato oficial del catálogo, como en todo lo demás.

La foto se borra en cuanto se ha usado, pase lo que pase — mismo criterio de minimización que
el ticket de la compra.
"""

from __future__ import annotations

import base64
import re
import uuid
from io import BytesIO
from pathlib import Path
from uuid import UUID

from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.ai import client as ai_client
from myfood.ai import tools
from myfood.ai.agent import AiAgentError, run_agent
from myfood.ai.flows.food_resolution import (
    build_candidates_payload,
    filter_restricted,
    resolve_food_mentions,
    search_candidates_for_text,
)
from myfood.ai.flows.web_estimate import estimate_missing_foods
from myfood.ai.prompts import (
    PLATE_PHOTO_PROMPT_VERSION,
    PLATE_PHOTO_SYSTEM_V1,
    SMART_LOG_SYSTEM_V2,
    build_plate_photo_resolution_prompt,
    build_plate_photo_vision_prompt,
)
from myfood.ai.queue import enqueue_plate_photo_job
from myfood.config import get_settings
from myfood.db.models import AiSession
from myfood.db.session import AdminSessionLocal
from myfood.errors import AppError

_VISION_TIMEOUT_SECONDS = 45.0
_RESOLUTION_TIMEOUT_SECONDS = 30.0
_MAX_IMAGE_BYTES = 10 * 1024 * 1024
_SUPPORTED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
# Claude tokeniza las imágenes en parches de 28×28 px: una foto de 1024 px de lado mayor son
# unos 1.000 tokens visuales. Subirla al máximo que admite el modelo (2576 px) la lleva a 4.784,
# casi cinco veces más, y para saber si eso es una tortilla no hace ninguna falta.
_MAX_SIDE_PX = 1024
# Lo que el modelo ponga entre paréntesis es una aclaración suya, no parte del nombre del
# alimento, y Meilisearch exige que TODOS los términos estén en el documento: con la
# coletilla dentro, «arroz blanco (forma clara)» no encuentra nada. El prompt ya pide que
# no las use; esto es la red por si las usa igualmente.
_PARENTHETICAL_RE = re.compile(r"\s*\([^)]*\)")
# Subcarpeta de `image_storage_path` (sección 12) — mismo disco compartido entre `api` y
# `worker` que las imágenes de alimentos y los tickets.
_PLATES_DIR = Path(get_settings().image_storage_path) / "plates"


async def request_plate_photo(
    session: AsyncSession,
    user_id: UUID,
    *,
    image_bytes: bytes,
    content_type: str,
    log_date: str,
    meal_type: str,
) -> AiSession:
    """Corre en el proceso `api` (regla 19): valida, normaliza la imagen y encola."""
    credential_status = await ai_client.get_credential_status(session)
    if not credential_status.configured:
        raise AppError(
            "AI_NOT_CONFIGURED",
            "El administrador todavía no ha configurado la credencial de iafood.",
            status_code=503,
        )
    if len(image_bytes) > _MAX_IMAGE_BYTES:
        raise AppError("IMAGE_TOO_LARGE", "La foto supera el tamaño máximo (10 MB).", 422)
    if content_type not in _SUPPORTED_CONTENT_TYPES:
        raise AppError("UNSUPPORTED_IMAGE_TYPE", "Formato de imagen no soportado.", 422)

    try:
        image = Image.open(BytesIO(image_bytes))
        image = image.convert("RGB")
    except Exception as exc:
        raise AppError("INVALID_IMAGE", "El archivo no es una imagen válida.", 422) from exc

    # Nunca se guarda el fichero subido tal cual (sección 12): se reescala y se elimina el EXIF
    # —que puede llevar geolocalización— reabriendo con Pillow y reexportando, no copiando los
    # bytes originales.
    image.thumbnail((_MAX_SIDE_PX, _MAX_SIDE_PX))
    _PLATES_DIR.mkdir(parents=True, exist_ok=True)
    image_path = _PLATES_DIR / f"{uuid.uuid4()}.jpg"
    image.save(image_path, format="JPEG", quality=85)

    ai_session = AiSession(
        user_id=user_id,
        kind="plate_photo",
        status="running",
        request_payload={
            "prompt_version": PLATE_PHOTO_PROMPT_VERSION,
            "image_path": str(image_path),
            "log_date": log_date,
            "meal_type": meal_type,
        },
    )
    session.add(ai_session)
    await session.commit()
    await session.refresh(ai_session)

    await enqueue_plate_photo_job(str(ai_session.id))
    return ai_session


async def process_plate_photo_job(ai_session_id: str) -> None:
    """Corre en el `worker` (regla 19)."""
    async with AdminSessionLocal() as session:
        ai_session = await session.get(AiSession, uuid.UUID(ai_session_id))
        if ai_session is None or ai_session.status != "running":
            return  # ya procesado, o no existe (defensivo)

        image_path = Path(ai_session.request_payload["image_path"])
        try:
            await _process(session, ai_session, image_path)
        finally:
            # La foto ya cumplió su función. No hay razón para conservarla, y el usuario no ha
            # pedido guardar una imagen: ha pedido registrar una comida.
            image_path.unlink(missing_ok=True)


def _clean_name(raw: object) -> str:
    """El nombre tal y como se va a buscar, sin las aclaraciones del modelo."""
    return _PARENTHETICAL_RE.sub("", str(raw or "")).strip()


async def _process(session: AsyncSession, ai_session: AiSession, image_path: Path) -> None:
    token = await ai_client.get_decrypted_token(session)
    if token is None:
        ai_session.status = "failed"
        ai_session.validation_errors = [
            {"code": "AI_NOT_CONFIGURED", "message": "La credencial se retiró tras encolar."}
        ]
        await session.commit()
        return

    try:
        image_b64 = base64.standard_b64encode(image_path.read_bytes()).decode()
    except OSError:
        ai_session.status = "failed"
        ai_session.validation_errors = [
            {"code": "IMAGE_GONE", "message": "La foto ya no está disponible."}
        ]
        await session.commit()
        return

    input_tokens = 0
    output_tokens = 0

    # --- Fase 1: qué se ve en el plato -----------------------------------------------------
    sink: list[dict] = []
    try:
        vision_result = await run_agent(
            token=token,
            prompt=build_plate_photo_vision_prompt(),
            system_prompt=PLATE_PHOTO_SYSTEM_V1,
            mcp_tools=[tools.build_describe_plate_tool(sink)],
            images=[("image/jpeg", image_b64)],
            # Tres no son de sobra: con 2 el CLI corta con «Reached maximum number of turns»
            # antes de que la llamada a la herramienta llegue a cerrarse (visto en vivo).
            max_turns=4,
            timeout_seconds=_VISION_TIMEOUT_SECONDS,
        )
    except AiAgentError as exc:
        ai_session.status = "failed"
        ai_session.validation_errors = [{"code": exc.code, "message": str(exc)}]
        await session.commit()
        return
    input_tokens += vision_result.input_tokens or 0
    output_tokens += vision_result.output_tokens or 0

    seen = sink[-1].get("alimentos", []) if sink else []
    if not seen:
        ai_session.status = "succeeded"
        ai_session.response_payload = {
            "items": [],
            "warning": "NO_FOOD_IN_PHOTO",
            "pregunta": None,
            "no_encontrados": [],
        }
        ai_session.input_tokens = input_tokens
        ai_session.output_tokens = output_tokens
        await session.commit()
        return

    # --- Fase 2: a qué alimentos del catálogo corresponden ---------------------------------
    # Se busca por el nombre de cada cosa vista, igual que el registro por texto busca por
    # cada mención. A partir de aquí el camino es exactamente el mismo.
    names = [_clean_name(food.get("nombre")) for food in seen]
    names = [name for name in names if name]
    hits = await search_candidates_for_text(", ".join(names))
    hits = await filter_restricted(session, ai_session.user_id, hits)
    if not hits:
        # Que el catálogo no tenga NADA de lo que hay en el plato es justo cuando más falta
        # hace el respaldo: antes se salía por aquí sin llegar a buscarlo.
        proposal, web_result = await estimate_missing_foods(
            session,
            token=token,
            user_id=ai_session.user_id,
            ai_session=ai_session,
            missing=names[:5],
            log_date=ai_session.request_payload["log_date"],
            meal_type=ai_session.request_payload["meal_type"],
        )
        if web_result is not None:
            input_tokens += web_result.input_tokens or 0
            output_tokens += web_result.output_tokens or 0
        ai_session.status = "succeeded"
        ai_session.response_payload = {
            "items": [],
            "warning": "NO_MATCH",
            "pregunta": None,
            "no_encontrados": names[:5],
            "proposal": proposal,
            "visto": seen,
        }
        ai_session.input_tokens = input_tokens
        ai_session.output_tokens = output_tokens
        await session.commit()
        return

    candidates_out, alias_to_food_id = build_candidates_payload(hits)
    try:
        items_out, resolution_result, extras = await resolve_food_mentions(
            session,
            token=token,
            prompt=build_plate_photo_resolution_prompt(seen, candidates_out),
            system_prompt=SMART_LOG_SYSTEM_V2,
            alias_to_food_id=alias_to_food_id,
            timeout_seconds=_RESOLUTION_TIMEOUT_SECONDS,
        )
    except AiAgentError as exc:
        ai_session.status = "failed"
        ai_session.validation_errors = [{"code": exc.code, "message": str(exc)}]
        await session.commit()
        return
    input_tokens += resolution_result.input_tokens or 0
    output_tokens += resolution_result.output_tokens or 0

    proposal, web_result = await estimate_missing_foods(
        session,
        token=token,
        user_id=ai_session.user_id,
        ai_session=ai_session,
        missing=extras["no_encontrados"],
        log_date=ai_session.request_payload["log_date"],
        meal_type=ai_session.request_payload["meal_type"],
    )
    if web_result is not None:
        input_tokens += web_result.input_tokens or 0
        output_tokens += web_result.output_tokens or 0

    ai_session.status = "succeeded"
    ai_session.response_payload = {
        "items": items_out,
        "warning": None if items_out else "NO_MATCH",
        "pregunta": extras["pregunta"],
        "no_encontrados": extras["no_encontrados"],
        "proposal": proposal,
        # Lo que la fase de visión creyó ver, tal cual. Se guarda porque es lo único que
        # explica una propuesta rara, y sin ello no hay forma de saber si falló el ojo o la
        # búsqueda en el catálogo.
        "visto": seen,
    }
    ai_session.input_tokens = input_tokens
    ai_session.output_tokens = output_tokens
    await session.commit()
