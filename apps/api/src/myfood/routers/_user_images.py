"""Endpoints comunes de imagen de usuario (recetas y suplementos): subir, servir y borrar."""

from __future__ import annotations

from uuid import UUID

from fastapi import UploadFile
from fastapi.responses import FileResponse

from myfood.errors import AppError
from myfood.services import user_images
from myfood.services.images import ImageRejected


async def store_uploaded_image(kind: str, owner_id: UUID, file: UploadFile) -> None:
    try:
        data = await user_images.read_upload(file)
        await user_images.save_upload(kind, owner_id, data)
    except user_images.ImageTooLarge as exc:
        raise AppError(
            "IMAGE_TOO_LARGE", "La imagen supera el máximo de 10 MB.", status_code=413
        ) from exc
    except ImageRejected as exc:
        raise AppError(
            "INVALID_IMAGE",
            "Solo se admiten imágenes JPEG, PNG, WebP o HEIC válidas.",
            status_code=422,
        ) from exc


def serve_image(kind: str, owner_id: UUID) -> FileResponse:
    path = user_images.image_path(kind, owner_id)
    if not path.exists():
        raise AppError("IMAGE_NOT_FOUND", "Todavía no tiene imagen.", status_code=404)
    # Privada: solo el propio usuario; se revalida cuando cambia la versión (?v=).
    return FileResponse(
        path, media_type="image/webp", headers={"Cache-Control": "private, max-age=3600"}
    )
