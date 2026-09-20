"""Imágenes de producto (documento 2, sección 12): proxy con caché perezosa en disco.

Nunca se descarga el dump de imágenes de Open Food Facts (terabytes): cuando alguien
pide la imagen de un producto se descarga UNA vez, se generan variantes WebP de 100, 200
y 400 px con Pillow y se sirve siempre desde disco. Si no hay imagen (o la descarga falla)
se sirve un placeholder por categoría con 200 OK — la interfaz nunca ve un hueco roto.

Seguridad: la URL remota solo puede ser de los dominios de imágenes de OFF y por HTTPS; se
limita el tamaño de la descarga y los píxeles decodificados (bombas de descompresión); el
formato se decide por la cabecera real del fichero, no por su extensión ni su Content-Type;
y las variantes se guardan sin EXIF (ni geolocalización).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import redis.asyncio as redis
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from myfood.ai.queue import enqueue_job
from myfood.config import get_settings
from myfood.db.models import Food, FoodImage

logger = logging.getLogger("myfood.images")

# Límite de descompresión de Pillow (sección 12: "activado"): ~40 megapíxeles.
Image.MAX_IMAGE_PIXELS = 40_000_000

IMAGE_TYPES = ("front", "ingredients", "nutrition", "packaging")
VARIANT_SIZES = (100, 200, 400)
ALLOWED_SIZES = (*VARIANT_SIZES, "full")
ALLOWED_REMOTE_HOSTS = ("images.openfoodfacts.org", "static.openfoodfacts.org")

MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 8.0
# La imagen de OFF tarda 8–10 s en llegar desde este servidor: la petición del usuario espera
# poco y, si no llega, sirve el placeholder y deja la descarga al worker (sección 12).
INLINE_DOWNLOAD_TIMEOUT_SECONDS = 2.5
WEBP_QUALITY = 82
# Formatos aceptados por su cabecera real (Pillow los identifica por los primeros bytes).
_ACCEPTED_FORMATS = {"JPEG", "PNG", "WEBP"}

IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"
PLACEHOLDER_CACHE_CONTROL = "public, max-age=3600"
# Placeholder de una imagen que se está descargando: que el navegador vuelva a pedirla enseguida.
PENDING_CACHE_CONTROL = "public, max-age=10"


class ImageRejected(Exception):
    """La imagen no es válida o no es segura de procesar."""


def validate_remote_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "") not in ALLOWED_REMOTE_HOSTS:
        raise ImageRejected("La URL de la imagen no es de un dominio permitido.")


async def download_remote_image(url: str, client: httpx.AsyncClient | None = None) -> bytes:
    validate_remote_url(url)
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=False)
    try:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            if not response.headers.get("content-type", "").startswith("image/"):
                raise ImageRejected("La respuesta no es una imagen.")
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise ImageRejected("La imagen supera el tamaño máximo (5 MB).")
                chunks.append(chunk)
            return b"".join(chunks)
    finally:
        if owns_client:
            await client.aclose()


def process_image(
    data: bytes, *, sizes: tuple[int, ...] = VARIANT_SIZES
) -> tuple[dict[int, bytes], tuple[int, int]]:
    """Variantes WebP (sin EXIF) por lado mayor, y las dimensiones del original."""
    try:
        with Image.open(BytesIO(data)) as probe:
            if probe.format not in _ACCEPTED_FORMATS:
                raise ImageRejected("Formato de imagen no admitido.")
        with Image.open(BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)  # respeta la orientación antes de quitar el EXIF
            original_size = image.size
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGB")
            if image.mode == "RGBA":
                background = Image.new("RGB", image.size, (255, 255, 255))
                background.paste(image, mask=image.getchannel("A"))
                image = background
            variants: dict[int, bytes] = {}
            for size in sizes:
                resized = image.copy()
                resized.thumbnail((size, size), Image.Resampling.LANCZOS)
                out = BytesIO()
                # Sin `exif=`: la variante no lleva metadatos.
                resized.save(out, format="WEBP", quality=WEBP_QUALITY, method=4)
                variants[size] = out.getvalue()
            return variants, original_size
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        raise ImageRejected("La imagen no se puede procesar.") from exc


def food_dir(root: Path, food_id: str) -> Path:
    return root / food_id[:2] / food_id


def variant_path(root: Path, food_id: str, image_type: str, size: int) -> Path:
    return food_dir(root, food_id) / f"{image_type}_{size}.webp"


def write_variants(root: Path, food_id: str, image_type: str, variants: dict[int, bytes]) -> int:
    """Escribe las variantes de forma atómica (temporal + rename) y devuelve los bytes totales."""
    directory = food_dir(root, food_id)
    directory.mkdir(parents=True, exist_ok=True)
    total = 0
    for size, payload in variants.items():
        final = variant_path(root, food_id, image_type, size)
        tmp = final.with_suffix(".tmp")
        tmp.write_bytes(payload)
        tmp.replace(final)
        total += len(payload)
    return total


def delete_variants(root: Path, food_id: str, image_type: str) -> None:
    for size in VARIANT_SIZES:
        variant_path(root, food_id, image_type, size).unlink(missing_ok=True)


# --- placeholder por categoría ----------------------------------------------------

# (patrón en la categoría, emoji). Las categorías vienen de USDA, CIQUAL, BEDCA y OFF
# (inglés, francés y español): se busca por palabras clave, en orden.
_PLACEHOLDER_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("fruit", "fruta", "fruits"), "🍎"),
    (("vegetable", "verdura", "legume", "légume", "hortaliza"), "🥦"),
    (
        (
            "beef",
            "pork",
            "lamb",
            "poultry",
            "meat",
            "sausage",
            "carne",
            "cárnico",
            "viande",
            "charcut",
            "ham",
            "jamón",
        ),
        "🥩",
    ),
    (("fish", "finfish", "shellfish", "seafood", "pescado", "marisco", "poisson"), "🐟"),
    (
        ("dairy", "milk", "cheese", "yogurt", "lácteo", "lait", "fromage", "egg", "huevo", "oeuf"),
        "🥛",
    ),
    (
        (
            "bread",
            "baked",
            "cereal",
            "pasta",
            "grain",
            "rice",
            "pan ",
            "bolleria",
            "biscuit",
            "cookie",
            "galleta",
        ),
        "🍞",
    ),
    (("beverage", "drink", "juice", "water", "coffee", "tea", "bebida", "boisson", "zumo"), "🥤"),
    (("nut", "seed", "fruto seco", "almond"), "🥜"),
    (("oil", "fat", "butter", "aceite", "grasa", "huile"), "🫒"),
    (
        ("sweet", "candy", "chocolate", "dessert", "sugar", "dulce", "bombón", "sucre", "snack"),
        "🍫",
    ),
    (("soup", "sauce", "gravy", "salsa", "sopa", "condiment", "spice", "especia"), "🥣"),
    (("baby", "infant", "bebé"), "🍼"),
)
_DEFAULT_PLACEHOLDER = "🍽️"


def placeholder_emoji(category: str | None) -> str:
    text = (category or "").lower()
    for keywords, emoji in _PLACEHOLDER_RULES:
        if any(k in text for k in keywords):
            return emoji
    return _DEFAULT_PLACEHOLDER


def placeholder_svg(category: str | None) -> bytes:
    emoji = placeholder_emoji(category)
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" role="img" '
        'aria-label="Sin imagen">'
        '<rect width="100" height="100" rx="14" fill="#f3f4f6"/>'
        '<text x="50" y="50" font-size="52" text-anchor="middle" '
        f'dominant-baseline="central">{emoji}</text>'
        "</svg>"
    )
    return svg.encode("utf-8")


def etag_for(path: Path) -> str:
    stat = path.stat()
    return hashlib.sha1(f"{path.name}:{stat.st_size}:{int(stat.st_mtime)}".encode()).hexdigest()  # noqa: S324


@dataclass
class ImageOutcome:
    """Qué servir: un fichero de la caché o un placeholder."""

    path: Path | None
    placeholder: bytes | None
    media_type: str
    cache_control: str


# --- orquestación: servir, descargar, cachear, purgar -----------------------------

IMAGE_JOBS_QUEUE_KEY = "images:jobs:fetch"
_NEGATIVE_TTL_SECONDS = 24 * 60 * 60
# Valor de la caché negativa: `retry` = fallo transitorio que reintenta el worker (el placeholder
# es provisional); `rejected` = imagen inválida (el placeholder es definitivo).
_NEGATIVE_RETRY = "retry"
_NEGATIVE_REJECTED = "rejected"
_LOCK_TTL_SECONDS = 30
_TOUCH_INTERVAL_SQL = "interval '1 hour'"
_redis = redis.from_url(get_settings().redis_url, decode_responses=True)


def storage_root() -> Path:
    return Path(get_settings().image_storage_path)


def _negative_key(food_id: str, image_type: str) -> str:
    return f"images:neg:{food_id}:{image_type}"


def _lock_key(food_id: str, image_type: str) -> str:
    return f"images:lock:{food_id}:{image_type}"


def placeholder_outcome(category: str | None, *, pending: bool = False) -> ImageOutcome:
    return ImageOutcome(
        path=None,
        placeholder=placeholder_svg(category),
        media_type="image/svg+xml",
        cache_control=PENDING_CACHE_CONTROL if pending else PLACEHOLDER_CACHE_CONTROL,
    )


def _file_outcome(path: Path) -> ImageOutcome:
    return ImageOutcome(
        path=path, placeholder=None, media_type="image/webp", cache_control=IMMUTABLE_CACHE_CONTROL
    )


async def _touch(session: AsyncSession, image: FoodImage) -> None:
    """`last_access_at` para la purga LRU, sin una escritura por cada petición."""
    await session.execute(
        text(
            "UPDATE food_images SET last_access_at = now() WHERE id = :id "
            f"AND (last_access_at IS NULL OR last_access_at < now() - {_TOUCH_INTERVAL_SQL})"
        ),
        {"id": str(image.id)},
    )
    await session.commit()


async def fetch_and_store(
    session: AsyncSession, image: FoodImage, *, timeout: float
) -> str:
    """Descarga `remote_url`, genera las variantes y registra la ruta. Devuelve `"stored"`
    (quedó en disco), `"rejected"` (la imagen no es válida: no merece reintento) o
    `"failed"` (red o tiempo: se puede reintentar en el worker). Un fallo NO se propaga:
    la petición del usuario sirve el placeholder."""
    if not image.remote_url:
        return "rejected"
    food_id = str(image.food_id)
    try:
        data = await asyncio.wait_for(download_remote_image(image.remote_url), timeout=timeout)
        variants, (width, height) = await asyncio.to_thread(process_image, data)
        total = await asyncio.to_thread(
            write_variants, storage_root(), food_id, image.type, variants
        )
    except (ImageRejected, httpx.HTTPError, TimeoutError, OSError) as exc:
        logger.info("imagen %s/%s no disponible: %s", food_id, image.type, exc)
        rejected = isinstance(exc, ImageRejected)
        await _redis.set(
            _negative_key(food_id, image.type),
            _NEGATIVE_REJECTED if rejected else _NEGATIVE_RETRY,
            ex=_NEGATIVE_TTL_SECONDS,
        )
        return "rejected" if rejected else "failed"
    await session.execute(
        update(FoodImage)
        .where(FoodImage.id == image.id)
        .values(
            local_path=str(food_dir(storage_root(), food_id).relative_to(storage_root())),
            width=width,
            height=height,
            bytes=total,
            last_access_at=datetime.now(UTC),
        )
    )
    await session.commit()
    return "stored"


async def resolve_image(
    session: AsyncSession, food: Food, image_type: str, size: int | str
) -> ImageOutcome:
    """Qué servir para `GET /foods/{id}/image` (sección 12). Nunca lanza por un fallo de
    descarga: sirve el placeholder de la categoría con 200 y, si merece la pena reintentar,
    encola la descarga en el worker."""
    px = 400 if size == "full" else int(size)
    food_id = str(food.id)
    image = await session.scalar(
        select(FoodImage).where(FoodImage.food_id == food.id, FoodImage.type == image_type)
    )
    if image is None:
        return placeholder_outcome(food.category)

    path = variant_path(storage_root(), food_id, image_type, px)
    if image.local_path and path.exists():
        await _touch(session, image)
        return _file_outcome(path)

    if not image.remote_url:
        return placeholder_outcome(food.category)
    negative = await _redis.get(_negative_key(food_id, image_type))
    if negative is not None:
        return placeholder_outcome(food.category, pending=negative == _NEGATIVE_RETRY)

    # Un solo intento simultáneo por imagen: los demás reciben el placeholder al momento.
    if not await _redis.set(_lock_key(food_id, image_type), "1", nx=True, ex=_LOCK_TTL_SECONDS):
        return placeholder_outcome(food.category, pending=True)
    try:
        status = await fetch_and_store(session, image, timeout=INLINE_DOWNLOAD_TIMEOUT_SECONDS)
    finally:
        await _redis.delete(_lock_key(food_id, image_type))
    if status == "stored":
        return _file_outcome(path)
    if status == "failed":
        # Lenta o caída ahora mismo: se sirve el placeholder y el worker lo reintenta
        # sin bloquear a nadie (sección 12: "nunca bloquear la petición del usuario").
        await enqueue_job(IMAGE_JOBS_QUEUE_KEY, f"{food_id}:{image_type}")
        return placeholder_outcome(food.category, pending=True)
    return placeholder_outcome(food.category)


async def process_image_job(payload: str) -> None:
    """Corre en el `worker`: reintenta una descarga que falló en la petición del usuario."""
    from myfood.db.session import AdminSessionLocal

    food_id, image_type = payload.split(":", 1)
    async with AdminSessionLocal() as session:
        image = await session.scalar(
            select(FoodImage).where(
                FoodImage.food_id == uuid.UUID(food_id), FoodImage.type == image_type
            )
        )
        if image is None or (
            image.local_path and variant_path(storage_root(), food_id, image_type, 200).exists()
        ):
            return
        await _redis.delete(_negative_key(food_id, image_type))
        await fetch_and_store(session, image, timeout=30.0)


async def purge_cache(
    session: AsyncSession, budget_bytes: int, *, target_ratio: float = 0.8
) -> int:
    """Purga LRU (sección 12): si lo cacheado supera el presupuesto, borra por
    `last_access_at` ascendente hasta bajar al 80 %. Borra los ficheros y deja
    `local_path = NULL` (se conserva `remote_url` para poder recuperarla). Devuelve
    cuántas imágenes purgó."""
    total = await session.scalar(
        select(func.coalesce(func.sum(FoodImage.bytes), 0)).where(FoodImage.local_path.is_not(None))
    )
    total = int(total or 0)
    if total <= budget_bytes:
        return 0
    goal = int(budget_bytes * target_ratio)
    rows = (
        await session.execute(
            select(FoodImage)
            .where(FoodImage.local_path.is_not(None))
            .order_by(FoodImage.last_access_at.asc().nulls_first())
        )
    ).scalars()
    purged = 0
    for image in rows:
        if total <= goal:
            break
        delete_variants(storage_root(), str(image.food_id), image.type)
        total -= int(image.bytes or 0)
        image.local_path = None
        image.bytes = None
        purged += 1
    await session.commit()
    return purged
