"""Registro por foto del plato.

Mismo criterio que el registro por texto y el chat, con una imagen en vez de una frase: el
modelo mira la foto y devuelve cada plato ENTERO con su desglose en gramos («bocadillo de
jamón»: pan 100 g, jamón serrano 40 g, aceite de oliva 5 g), y después cada parte se contrasta
con el catálogo (`domain/catalog_refine.py`) para tomar de ahí sus calorías, macros y
micronutrientes cuando hay un alimento que encaja. Lo que el catálogo no confirma se queda
con la estimación del modelo. El resultado es una propuesta de diario que el usuario aprueba
o rechaza entera, con la misma tarjeta que en los otros dos sitios.

Es UNA llamada al modelo. Antes eran dos (describir la foto sin cifras, y luego elegir entre
candidatos del catálogo) más una tercera de búsqueda web para lo que faltaba, y en producción
no terminó bien ni una sola vez: las tres fotos que se subieron agotaron el tiempo de espera o
se quedaron huérfanas. Sin búsqueda web por la misma razón que en el texto: el modelo ya sabe
lo que lleva un plato corriente.

La foto se borra en cuanto se ha usado, pase lo que pase — mismo criterio de minimización que
el ticket de la compra.
"""

from __future__ import annotations

import base64
import uuid
from io import BytesIO
from pathlib import Path
from uuid import UUID

from PIL import Image, ImageOps
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.ai import client as ai_client
from myfood.ai.agent import AiAgentError
from myfood.ai.flows.meal_estimate import estimate_meal, response_payload, store_proposal
from myfood.ai.prompts import (
    PLATE_PHOTO_PROMPT_VERSION,
    PLATE_PHOTO_SYSTEM_V2,
    build_plate_photo_prompt,
)
from myfood.ai.queue import enqueue_plate_photo_job
from myfood.config import get_settings
from myfood.db.models import AiSession
from myfood.db.session import AdminSessionLocal
from myfood.domain import estimated_dishes
from myfood.errors import AppError

# Medido con fotos reales: mirar la foto y escribir cada plato con su desglose tarda entre 15
# y 30 s. Con 45 s —lo que había— una foto con muchas cosas se quedaba fuera.
_VISION_TIMEOUT_SECONDS = 80.0
_MAX_IMAGE_BYTES = 10 * 1024 * 1024
_SUPPORTED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
# Claude tokeniza las imágenes en parches de 28×28 px: una foto de 1024 px de lado mayor son
# unos 1.000 tokens visuales. Subirla al máximo que admite el modelo (2576 px) la lleva a 4.784,
# casi cinco veces más, y para saber si eso es una tortilla no hace ninguna falta.
_MAX_SIDE_PX = 1024
# Los platos guardados que se le nombran al modelo, por si lo de la foto es uno de ellos.
_MAX_KNOWN_DISHES = 30
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
        # La orientación de una foto de móvil va en el EXIF, que se tira a continuación: sin
        # aplicarla antes, una foto hecha en vertical le llegaba al modelo tumbada.
        image = ImageOps.exif_transpose(image)
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


async def _fail(session: AsyncSession, ai_session: AiSession, code: str, message: str) -> None:
    ai_session.status = "failed"
    ai_session.validation_errors = [{"code": code, "message": message}]
    await session.commit()


async def _process(session: AsyncSession, ai_session: AiSession, image_path: Path) -> None:
    token = await ai_client.get_decrypted_token(session)
    if token is None:
        await _fail(
            session, ai_session, "AI_NOT_CONFIGURED", "La credencial se retiró tras encolar."
        )
        return

    try:
        image_b64 = base64.standard_b64encode(image_path.read_bytes()).decode()
    except OSError:
        await _fail(session, ai_session, "IMAGE_GONE", "La foto ya no está disponible.")
        return

    saved = await estimated_dishes.load_saved(session)
    known = [dish.name for dish in saved.values()][:_MAX_KNOWN_DISHES]
    try:
        args, result = await estimate_meal(
            token=token,
            prompt=build_plate_photo_prompt(known),
            system_prompt=PLATE_PHOTO_SYSTEM_V2,
            timeout_seconds=_VISION_TIMEOUT_SECONDS,
            images=[("image/jpeg", image_b64)],
        )
    except AiAgentError as exc:
        await _fail(session, ai_session, exc.code, str(exc))
        return

    ai_session.input_tokens = result.input_tokens
    ai_session.output_tokens = result.output_tokens
    question = str(args.get("pregunta") or "").strip() or None
    dishes = [dish for dish in args.get("platos") or [] if isinstance(dish, dict)]

    proposal: dict | None = None
    if dishes:
        request_payload = ai_session.request_payload
        try:
            proposal = await store_proposal(
                session,
                ai_session,
                {
                    "date": request_payload["log_date"],
                    "meal_type": request_payload["meal_type"],
                    "request": None,
                    "items": dishes,
                },
            )
        except AppError as exc:
            # Un mensaje honesto de por qué no se puede, en vez de apuntar algo dudoso.
            await _fail(session, ai_session, exc.code, exc.message)
            return

    ai_session.status = "succeeded"
    ai_session.response_payload = {
        **response_payload(proposal, question=question, empty_warning="NO_FOOD_IN_PHOTO"),
        # Lo que el modelo dijo ver, tal cual, antes de afinarlo con el catálogo. Se guarda
        # porque es lo único que explica una propuesta rara: sin ello no hay forma de saber
        # si falló el ojo o el afinado.
        "visto": dishes,
    }
    await session.commit()
