"""Imágenes de producto (`services/images.py` + `GET /foods/{id}/image`, sección 12)."""

import uuid
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from PIL import Image
from sqlalchemy import select, text

from myfood.db.models import FoodImage
from myfood.db.session import AdminSessionLocal
from myfood.services import images as svc

pytestmark = pytest.mark.asyncio

OFF_URL = "https://images.openfoodfacts.org/images/products/848/front_es.4.400.jpg"


def _jpeg(width=1200, height=800, *, exif: bool = False, orientation: int | None = None) -> bytes:
    image = Image.new("RGB", (width, height), (200, 30, 30))
    out = BytesIO()
    kwargs = {}
    if exif:
        data = Image.Exif()
        data[0x010F] = "CamaraSecreta"  # Make
        if orientation:
            data[0x0112] = orientation
        data[0x8825] = {1: "N", 2: (40.0, 26.0, 0.0), 3: "W", 4: (3.0, 42.0, 0.0)}  # GPS
        kwargs["exif"] = data
    image.save(out, format="JPEG", **kwargs)
    return out.getvalue()


# --- process_image ---------------------------------------------------------------


def test_variants_are_webp_bounded_by_size_and_carry_no_exif():
    variants, original = svc.process_image(_jpeg(exif=True))

    assert original == (1200, 800)
    assert set(variants) == {100, 200, 400}
    for size, payload in variants.items():
        with Image.open(BytesIO(payload)) as img:
            assert img.format == "WEBP"
            assert max(img.size) <= size
            assert not img.getexif(), "la variante no debe llevar EXIF (ni geolocalización)"
            assert b"CamaraSecreta" not in payload


def test_exif_orientation_is_applied_before_the_metadata_is_dropped():
    # 400x200 marcada como rotada 90° (orientación 6) debe salir vertical (alto > ancho).
    variants, original = svc.process_image(_jpeg(400, 200, exif=True, orientation=6))

    with Image.open(BytesIO(variants[400])) as img:
        assert img.height > img.width
    assert original == (200, 400)


def test_transparent_png_is_flattened_on_white():
    rgba = Image.new("RGBA", (50, 50), (0, 0, 0, 0))
    out = BytesIO()
    rgba.save(out, format="PNG")

    variants, _ = svc.process_image(out.getvalue())

    with Image.open(BytesIO(variants[100])) as img:
        assert img.convert("RGB").getpixel((5, 5)) == (255, 255, 255)


def test_non_images_and_unlisted_formats_are_rejected_by_their_real_header():
    with pytest.raises(svc.ImageRejected):
        svc.process_image(b"esto no es una imagen, aunque se llame foto.jpg")
    gif = BytesIO()
    Image.new("P", (10, 10)).save(gif, format="GIF")
    with pytest.raises(svc.ImageRejected):
        svc.process_image(gif.getvalue())


def test_a_decompression_bomb_is_rejected(monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)  # 100x100 = 10.000 px > 2 x límite
    with pytest.raises(svc.ImageRejected):
        svc.process_image(_jpeg(100, 100))


# --- URL remota y descarga --------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        OFF_URL,
        "https://static.openfoodfacts.org/images/x.jpg",
    ],
)
def test_off_image_domains_are_allowed(url):
    svc.validate_remote_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://images.openfoodfacts.org/x.jpg",  # sin HTTPS
        "https://evil.example/x.jpg",
        "https://images.openfoodfacts.org.evil.example/x.jpg",  # sufijo engañoso
        "https://images.openfoodfacts.org@evil.example/x.jpg",  # userinfo
        "https://169.254.169.254/latest/meta-data/",
        "file:///etc/passwd",
    ],
)
def test_other_urls_are_refused(url):
    with pytest.raises(svc.ImageRejected):
        svc.validate_remote_url(url)


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_download_returns_the_bytes_of_an_image():
    async def _run():
        client = _client(
            lambda r: httpx.Response(200, content=b"abc", headers={"content-type": "image/jpeg"})
        )
        try:
            return await svc.download_remote_image(OFF_URL, client)
        finally:
            await client.aclose()

    assert await _run() == b"abc"


async def test_download_refuses_non_image_content_type():
    client = _client(
        lambda r: httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"})
    )
    with pytest.raises(svc.ImageRejected):
        await svc.download_remote_image(OFF_URL, client)
    await client.aclose()


async def test_download_refuses_more_than_5_mb():
    big = b"x" * (svc.MAX_DOWNLOAD_BYTES + 1)
    client = _client(
        lambda r: httpx.Response(200, content=big, headers={"content-type": "image/jpeg"})
    )
    with pytest.raises(svc.ImageRejected):
        await svc.download_remote_image(OFF_URL, client)
    await client.aclose()


# --- placeholder y rutas de fichero -----------------------------------------------


@pytest.mark.parametrize(
    ("category", "emoji"),
    [
        ("Fruits and Fruit Juices", "🍎"),
        ("Cárnicos y derivados", "🥩"),
        ("produits à base de poissons et produits de la mer", "🐟"),
        ("Dairy and Egg Products", "🥛"),
        ("Baked Products", "🍞"),
        ("Beverages", "🥤"),
        (None, "🍽️"),
        ("categoría desconocida xyz", "🍽️"),
    ],
)
def test_placeholder_emoji_by_category(category, emoji):
    assert svc.placeholder_emoji(category) == emoji


def test_placeholder_is_a_valid_svg():
    root = ET.fromstring(svc.placeholder_svg("Beverages"))
    assert root.tag.endswith("svg")


def test_variant_paths_are_sharded_by_the_first_two_characters_of_the_id(tmp_path):
    food_id = "ab12cd34-0000-0000-0000-000000000000"
    path = svc.variant_path(tmp_path, food_id, "front", 200)
    assert path == tmp_path / "ab" / food_id / "front_200.webp"


def test_variants_are_written_atomically_and_can_be_deleted(tmp_path):
    food_id = str(uuid.uuid4())
    total = svc.write_variants(tmp_path, food_id, "front", {100: b"a" * 10, 200: b"b" * 20})
    assert total == 30
    assert not list(tmp_path.rglob("*.tmp"))
    svc.delete_variants(tmp_path, food_id, "front")
    assert not list(tmp_path.rglob("*.webp"))


# --- endpoint --------------------------------------------------------------------


@pytest_asyncio.fixture
async def image_env(tmp_path, monkeypatch):
    """Caché en un directorio temporal, descarga simulada y cola simulada."""
    monkeypatch.setattr(svc, "storage_root", lambda: tmp_path)
    state = {"downloads": 0, "enqueued": [], "payload": _jpeg(), "error": None}

    async def _download(url, client=None):
        state["downloads"] += 1
        if state["error"] is not None:
            raise state["error"]
        return state["payload"]

    async def _enqueue(queue_key, payload):
        state["enqueued"].append((queue_key, payload))

    monkeypatch.setattr(svc, "download_remote_image", _download)
    monkeypatch.setattr(svc, "enqueue_job", _enqueue)
    yield state, tmp_path
    keys = [key async for key in svc._redis.scan_iter(match="images:*")]
    if keys:
        await svc._redis.delete(*keys)


async def _add_image(
    food_id, *, remote_url=OFF_URL, attribution="Open Food Facts", license="CC BY-SA"
):
    async with AdminSessionLocal() as session:
        session.add(
            FoodImage(
                food_id=food_id,
                type="front",
                remote_url=remote_url,
                source="off",
                license=license,
                attribution=attribution,
            )
        )
        await session.commit()


async def test_food_without_image_gets_the_category_placeholder_with_200(
    registered_client, test_food
):
    client, _ = registered_client
    resp = await client.get(f"/api/foods/{test_food}/image")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")
    assert "max-age=3600" in resp.headers["cache-control"]
    assert "immutable" not in resp.headers["cache-control"]


async def test_first_request_downloads_and_caches_then_serves_from_disk(
    registered_client, test_food, image_env
):
    client, _ = registered_client
    state, root = image_env
    await _add_image(test_food)

    first = await client.get(f"/api/foods/{test_food}/image?size=200")
    assert first.status_code == 200
    assert first.headers["content-type"] == "image/webp"
    assert "immutable" in first.headers["cache-control"]
    assert state["downloads"] == 1
    assert (root / str(test_food)[:2] / str(test_food) / "front_200.webp").exists()

    second = await client.get(f"/api/foods/{test_food}/image?size=100")
    assert second.status_code == 200
    assert second.headers["content-type"] == "image/webp"
    assert state["downloads"] == 1, "la segunda petición sale de disco, sin volver a descargar"

    async with AdminSessionLocal() as session:
        row = await session.scalar(select(FoodImage).where(FoodImage.food_id == test_food))
    assert row.local_path and row.bytes and row.width == 1200 and row.height == 800
    assert row.remote_url == OFF_URL  # se conserva para poder recuperarla


async def test_a_failed_download_serves_the_placeholder_queues_a_retry_and_is_not_repeated(
    registered_client, test_food, image_env
):
    client, _ = registered_client
    state, _root = image_env
    state["error"] = httpx.ConnectError("sin red")
    await _add_image(test_food)

    resp = await client.get(f"/api/foods/{test_food}/image")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")
    assert state["enqueued"] == [(svc.IMAGE_JOBS_QUEUE_KEY, f"{test_food}:front")]

    again = await client.get(f"/api/foods/{test_food}/image")
    assert again.headers["content-type"].startswith("image/svg+xml")
    assert state["downloads"] == 1, "la caché negativa evita reintentar en cada petición"


async def test_an_invalid_image_is_not_retried_by_the_worker(
    registered_client, test_food, image_env
):
    client, _ = registered_client
    state, _root = image_env
    state["payload"] = b"esto no es una imagen"
    await _add_image(test_food)

    resp = await client.get(f"/api/foods/{test_food}/image")
    assert resp.headers["content-type"].startswith("image/svg+xml")
    assert state["enqueued"] == []


async def test_the_worker_job_retries_and_stores_the_image(registered_client, test_food, image_env):
    client, _ = registered_client
    state, root = image_env
    state["error"] = httpx.ConnectError("sin red")
    await _add_image(test_food)
    await client.get(f"/api/foods/{test_food}/image")  # falla y deja caché negativa

    state["error"] = None  # la red vuelve
    await svc.process_image_job(f"{test_food}:front")

    assert (root / str(test_food)[:2] / str(test_food) / "front_400.webp").exists()
    served = await client.get(f"/api/foods/{test_food}/image?size=400")
    assert served.headers["content-type"] == "image/webp"


async def test_image_endpoint_validates_type_size_and_food(registered_client, test_food):
    client, _ = registered_client
    assert (await client.get(f"/api/foods/{test_food}/image?type=hack")).status_code == 422
    assert (await client.get(f"/api/foods/{test_food}/image?size=999")).status_code == 422
    missing = await client.get(f"/api/foods/{uuid.uuid4()}/image")
    assert missing.status_code == 404


async def test_image_endpoint_requires_a_session(test_food):
    from httpx import ASGITransport, AsyncClient

    from myfood.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as anon:
        assert (await anon.get(f"/api/foods/{test_food}/image")).status_code == 401


async def test_food_detail_carries_the_image_credit(registered_client, test_food):
    client, _ = registered_client
    assert (await client.get(f"/api/foods/{test_food}")).json()["image_credit"] is None
    await _add_image(test_food)
    body = (await client.get(f"/api/foods/{test_food}")).json()
    assert body["image_credit"] == "Open Food Facts (CC BY-SA)"


# --- purga LRU ---------------------------------------------------------------------


async def test_lru_purge_deletes_the_least_recently_used_down_to_80_percent(
    superuser_conn, tmp_path, monkeypatch
):
    monkeypatch.setattr(svc, "storage_root", lambda: tmp_path)
    food_ids = [uuid.uuid4() for _ in range(3)]
    for i, food_id in enumerate(food_ids):
        await superuser_conn.execute(
            text(
                "INSERT INTO foods (id, kind, source, source_id, license, name_es, quality_rank) "
                "VALUES (:id, 'generic', 'test', :sid, 'CC0', :n, 1)"
            ),
            {"id": str(food_id), "sid": str(food_id), "n": f"Purga {i} (test)"},
        )
        svc.write_variants(
            tmp_path, str(food_id), "front", {100: b"x" * 100, 200: b"y" * 100, 400: b"z" * 100}
        )
        await superuser_conn.execute(
            text(
                "INSERT INTO food_images "
                "(food_id, type, remote_url, local_path, source, bytes, last_access_at) "
                "VALUES (:f, 'front', :u, :p, 'off', 300, now() - make_interval(hours => :h))"
            ),
            {"f": str(food_id), "u": OFF_URL, "p": str(food_id)[:2], "h": (3 - i) * 10},
        )
    await superuser_conn.commit()
    try:
        async with AdminSessionLocal() as session:
            # 900 B cacheados, presupuesto 500: objetivo 400 -> hay que borrar 2 (las más antiguas).
            purged = await svc.purge_cache(session, budget_bytes=500)
        assert purged == 2
        async with AdminSessionLocal() as session:
            rows = {
                r.food_id: r
                for r in (
                    await session.scalars(select(FoodImage).where(FoodImage.food_id.in_(food_ids)))
                )
            }
        assert rows[food_ids[0]].local_path is None and rows[food_ids[1]].local_path is None
        assert rows[food_ids[2]].local_path is not None, "la más reciente se conserva"
        assert rows[food_ids[0]].remote_url == OFF_URL, "se conserva para poder recuperarla"
        assert not list(Path(tmp_path, str(food_ids[0])[:2], str(food_ids[0])).glob("*.webp"))
        assert list(Path(tmp_path, str(food_ids[2])[:2], str(food_ids[2])).glob("*.webp"))
    finally:
        await superuser_conn.execute(
            text("DELETE FROM foods WHERE id = ANY(:ids)"), {"ids": [str(i) for i in food_ids]}
        )
        await superuser_conn.commit()


async def test_purge_does_nothing_under_budget(superuser_conn, tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "storage_root", lambda: tmp_path)
    async with AdminSessionLocal() as session:
        assert await svc.purge_cache(session, budget_bytes=10**12) == 0
