"""Imágenes que sube el usuario (recetas y suplementos): validación, EXIF, tamaño y privacidad."""

import io
import uuid

import pytest
from PIL import Image

from myfood.config import get_settings
from myfood.services import user_images

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def image_root(tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_STORAGE_PATH", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def _jpeg(size=(1600, 1200), *, exif=False, fmt="JPEG"):
    image = Image.new("RGB", size, (200, 30, 30))
    out = io.BytesIO()
    kwargs = {}
    if exif:
        data = Image.Exif()
        data[0x010F] = "SecretCameraMaker"
        data[0x8825] = {1: "N", 2: (40.0, 26.0, 46.0)}  # bloque GPS
        kwargs["exif"] = data
    image.save(out, format=fmt, **kwargs)
    return out.getvalue()


async def _recipe(client):
    resp = await client.post("/api/recipes", json={"name": "Con foto", "servings": 1})
    return resp.json()


async def _supplement(client):
    resp = await client.post(
        "/api/supplements",
        json={"name": "Creatina", "type": "sports", "dose_amount": 5, "dose_unit": "g"},
    )
    return resp.json()


def _upload(client, url, data, name="foto.jpg", content_type="image/jpeg"):
    return client.put(url, files={"file": (name, data, content_type)})


@pytest.mark.parametrize("kind", ["recipe", "supplement"])
async def test_an_uploaded_image_is_cleaned_resized_and_served_back(registered_client, kind):
    client, _ = registered_client
    owner = await (_recipe if kind == "recipe" else _supplement)(client)
    base = f"/api/{'recipes' if kind == 'recipe' else 'supplements'}/{owner['id']}"

    up = await _upload(client, f"{base}/image", _jpeg(exif=True))
    assert up.status_code == 204

    served = await client.get(f"{base}/image")
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/webp"
    assert served.headers["cache-control"].startswith("private")
    image = Image.open(io.BytesIO(served.content))
    assert image.format == "WEBP"
    assert max(image.size) == 1024  # 1600x1200 -> 1024x768
    assert not image.getexif(), "el EXIF (cámara, GPS) se elimina siempre"
    assert b"SecretCameraMaker" not in served.content
    detail = (await client.get(base)).json()
    assert detail["image_url"].startswith(f"{base}/image?v=")


async def test_an_image_smaller_than_the_limit_is_not_enlarged(registered_client):
    client, _ = registered_client
    recipe = await _recipe(client)
    await _upload(client, f"/api/recipes/{recipe['id']}/image", _jpeg((300, 200)))
    served = await client.get(f"/api/recipes/{recipe['id']}/image")
    assert Image.open(io.BytesIO(served.content)).size == (300, 200)


async def test_png_and_webp_are_accepted(registered_client):
    client, _ = registered_client
    recipe = await _recipe(client)
    url = f"/api/recipes/{recipe['id']}/image"
    assert (await _upload(client, url, _jpeg(fmt="PNG"), "a.png", "image/png")).status_code == 204
    assert (
        await _upload(client, url, _jpeg(fmt="WEBP"), "a.webp", "image/webp")
    ).status_code == 204


async def test_heic_is_accepted(registered_client):
    pillow_heif = pytest.importorskip("pillow_heif")
    client, _ = registered_client
    recipe = await _recipe(client)
    buffer = io.BytesIO()
    pillow_heif.from_pillow(Image.new("RGB", (64, 64), (10, 200, 10))).save(buffer, format="HEIF")
    resp = await _upload(
        client, f"/api/recipes/{recipe['id']}/image", buffer.getvalue(), "a.heic", "image/heic"
    )
    assert resp.status_code == 204


async def test_the_real_format_decides_not_the_extension_or_content_type(registered_client):
    client, _ = registered_client
    recipe = await _recipe(client)
    url = f"/api/recipes/{recipe['id']}/image"

    fake = await _upload(client, url, b"<script>alert(1)</script>", "trampa.jpg", "image/jpeg")
    assert fake.status_code == 422
    assert fake.json()["error"]["code"] == "INVALID_IMAGE"

    gif = io.BytesIO()
    Image.new("RGB", (8, 8)).save(gif, format="GIF")
    assert (await _upload(client, url, gif.getvalue(), "a.png", "image/png")).status_code == 422

    disguised = await _upload(client, url, _jpeg(), "a.exe", "application/octet-stream")
    assert disguised.status_code == 204, (
        "un JPEG válido con extensión rara se acepta: manda la cabecera"
    )


async def test_an_empty_file_is_rejected(registered_client):
    client, _ = registered_client
    recipe = await _recipe(client)
    resp = await _upload(client, f"/api/recipes/{recipe['id']}/image", b"")
    assert resp.status_code == 422


async def test_a_file_over_ten_megabytes_is_rejected(registered_client):
    client, _ = registered_client
    recipe = await _recipe(client)
    huge = _jpeg() + b"\0" * (user_images.MAX_UPLOAD_BYTES + 1)
    resp = await _upload(client, f"/api/recipes/{recipe['id']}/image", huge)
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "IMAGE_TOO_LARGE"


async def test_a_decompression_bomb_is_rejected(registered_client):
    client, _ = registered_client
    recipe = await _recipe(client)
    bomb = io.BytesIO()
    Image.new("1", (9000, 9000)).save(bomb, format="PNG")  # 81 Mpx, pesa muy poco
    assert bomb.tell() < 1_000_000
    resp = await _upload(client, f"/api/recipes/{recipe['id']}/image", bomb.getvalue(), "b.png")
    assert resp.status_code == 422


async def test_an_image_can_be_replaced_and_deleted(registered_client):
    client, _ = registered_client
    recipe = await _recipe(client)
    base = f"/api/recipes/{recipe['id']}"
    await _upload(client, f"{base}/image", _jpeg((400, 400)))
    await _upload(client, f"{base}/image", _jpeg((200, 100)))
    assert Image.open(io.BytesIO((await client.get(f"{base}/image")).content)).size == (200, 100)

    assert (await client.delete(f"{base}/image")).status_code == 204
    assert (await client.get(f"{base}/image")).status_code == 404
    assert (await client.get(base)).json()["image_url"] is None


async def test_images_are_private_to_their_owner(registered_client, fresh_client):
    client, _ = registered_client
    other, _ = fresh_client
    recipe = await _recipe(client)
    base = f"/api/recipes/{recipe['id']}"
    await _upload(client, f"{base}/image", _jpeg())

    assert (await other.get(f"{base}/image")).status_code == 404
    assert (await _upload(other, f"{base}/image", _jpeg())).status_code == 404
    assert (await other.delete(f"{base}/image")).status_code == 404
    assert (await client.get(f"{base}/image")).status_code == 200


async def test_deleting_the_owner_removes_the_file(registered_client):
    client, _ = registered_client
    recipe = await _recipe(client)
    await _upload(client, f"/api/recipes/{recipe['id']}/image", _jpeg())
    path = user_images.image_path("recipe", uuid.UUID(recipe["id"]))
    assert path.exists()

    await client.delete(f"/api/recipes/{recipe['id']}")

    assert not path.exists()


async def test_deleting_the_account_removes_every_photo(registered_client):
    client, _ = registered_client
    recipe = await _recipe(client)
    supplement = await _supplement(client)
    await _upload(client, f"/api/recipes/{recipe['id']}/image", _jpeg())
    await _upload(client, f"/api/supplements/{supplement['id']}/image", _jpeg())
    paths = [
        user_images.image_path("recipe", uuid.UUID(recipe["id"])),
        user_images.image_path("supplement", uuid.UUID(supplement["id"])),
    ]
    assert all(p.exists() for p in paths)

    resp = await client.post("/api/privacy/delete-account", json={"password": "correcthorse123"})

    assert resp.status_code == 204
    assert not any(p.exists() for p in paths)


async def test_uploads_need_a_session(registered_client):
    from httpx import ASGITransport, AsyncClient

    from myfood.main import app

    client, _ = registered_client
    recipe = await _recipe(client)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as anon:
        resp = await anon.put(
            f"/api/recipes/{recipe['id']}/image", files={"file": ("a.jpg", _jpeg(), "image/jpeg")}
        )
    assert resp.status_code == 401


async def test_an_image_just_over_the_pixel_limit_is_rejected_too(registered_client):
    client, _ = registered_client
    recipe = await _recipe(client)
    big = io.BytesIO()
    Image.new("1", (7000, 7000)).save(big, format="PNG")  # 49 Mpx: entre el límite y el doble
    resp = await _upload(client, f"/api/recipes/{recipe['id']}/image", big.getvalue(), "b.png")
    assert resp.status_code == 422
