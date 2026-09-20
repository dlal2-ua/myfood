"""Imágenes que sube el usuario (recetas y suplementos) — documento 2, sección 12.

- Máximo 10 MB; solo JPEG, PNG, WebP y HEIC, decididos por la cabecera real del fichero (no por la
  extensión ni el `Content-Type` declarado).
- Los metadatos EXIF —incluida la geolocalización— se eliminan SIEMPRE: la imagen se decodifica,
  se reescala a 1024 px de lado mayor y se guarda de nuevo como WebP. El original no se conserva.
- Privadas: solo las sirve el API al propio usuario.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

from myfood.config import get_settings
from myfood.services.images import ImageRejected, process_image

try:  # HEIC (fotos del iPhone): soporte opcional de Pillow
    import pillow_heif

    pillow_heif.register_heif_opener()
    _HEIF_AVAILABLE = True
except ImportError:  # pragma: no cover - la dependencia está en pyproject
    _HEIF_AVAILABLE = False

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
UPLOAD_MAX_SIDE = 1024
KINDS = ("recipe", "supplement")
_ACCEPTED = {"JPEG", "PNG", "WEBP"} | ({"HEIF"} if _HEIF_AVAILABLE else set())


class ImageTooLarge(Exception):
    """El fichero supera los 10 MB."""


def _root() -> Path:
    return Path(get_settings().image_storage_path) / "user"


def image_path(kind: str, owner_id: UUID | str) -> Path:
    owner = str(owner_id)
    return _root() / kind / owner[:2] / f"{owner}.webp"


def image_version(kind: str, owner_id: UUID | str) -> int | None:
    """Marca de versión (para invalidar la caché al cambiar la imagen); `None` si no hay imagen."""
    try:
        return int(image_path(kind, owner_id).stat().st_mtime)
    except FileNotFoundError:
        return None


def image_url(base: str, kind: str, owner_id: UUID | str) -> str | None:
    version = image_version(kind, owner_id)
    return f"{base}/image?v={version}" if version is not None else None


def _process(data: bytes) -> bytes:
    variants, _size = process_image(data, sizes=(UPLOAD_MAX_SIDE,), accepted_formats=_ACCEPTED)
    return variants[UPLOAD_MAX_SIDE]


async def save_upload(kind: str, owner_id: UUID | str, data: bytes) -> None:
    """Valida, limpia y guarda la imagen; lanza `ImageTooLarge` o `ImageRejected`."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageTooLarge
    if not data:
        raise ImageRejected("El fichero está vacío.")
    webp = await asyncio.to_thread(_process, data)
    final = image_path(kind, owner_id)
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.with_suffix(".tmp")
    tmp.write_bytes(webp)
    tmp.replace(final)


def delete_image(kind: str, owner_id: UUID | str) -> None:
    image_path(kind, owner_id).unlink(missing_ok=True)


async def read_upload(file) -> bytes:
    """Lee un `UploadFile` sin cargar en memoria más de `MAX_UPLOAD_BYTES`."""
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageTooLarge
    return data
