"""Registro por foto del plato (`ai/flows/plate_photo.py`).

La llamada real al modelo se simula: lo que hay que probar aquí es que la foto se normaliza y
se borra, que es UNA llamada con la imagen, y que lo que sale es una propuesta de diario con
cada plato entero y su desglose afinado con el catálogo — lo mismo que en el registro por
texto. Que el modelo *vea* de verdad se comprueba en vivo (`apps/web/e2e/plate-photo.cjs`).
"""

import uuid
from io import BytesIO
from pathlib import Path

import pytest
import pytest_asyncio
from PIL import Image
from sqlalchemy import text

from myfood.ai import client as ai_client
from myfood.ai.agent import AgentResult, AiAgentError
from myfood.ai.flows import meal_estimate
from myfood.ai.flows import plate_photo as flow
from myfood.ai.prompts import PLATE_PHOTO_SYSTEM_V2
from myfood.db.models import AiProposal, AiSession
from myfood.db.session import AdminSessionLocal
from myfood.errors import AppError

pytestmark = pytest.mark.asyncio


def _photo_bytes(size=(1800, 1400), fmt="JPEG") -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, (200, 180, 140)).save(buf, format=fmt)
    return buf.getvalue()


@pytest_asyncio.fixture
async def configured_credential(two_users):
    admin_id, _ = two_users
    async with AdminSessionLocal() as session:
        await ai_client.set_credential(session, admin_user_id=admin_id, token="fake-test-token")
    yield
    async with AdminSessionLocal() as session:
        await session.execute(text("DELETE FROM ai_credentials"))
        await session.commit()


@pytest.fixture(autouse=True)
def _plates_dir(tmp_path, monkeypatch):
    """`image_storage_path` es `/data/images` dentro del contenedor y no existe aquí — mismo
    apaño que en los tests del escaneo de tickets."""
    monkeypatch.setattr(flow, "_PLATES_DIR", tmp_path / "plates")


async def _request(user_id, **kwargs):
    async with AdminSessionLocal() as session:
        return await flow.request_plate_photo(
            session,
            user_id,
            image_bytes=kwargs.pop("image_bytes", _photo_bytes()),
            content_type=kwargs.pop("content_type", "image/jpeg"),
            log_date=kwargs.pop("log_date", "2026-09-24"),
            meal_type=kwargs.pop("meal_type", "lunch"),
        )


async def _reload(session_id) -> AiSession:
    async with AdminSessionLocal() as session:
        return await session.get(AiSession, session_id)


# --- subida ---------------------------------------------------------------------------------


async def test_la_foto_se_reescala_y_pierde_el_exif(two_users, configured_credential):
    """A 1024 px de lado mayor son ~1.000 tokens visuales; al máximo del modelo serían 4.784,
    casi cinco veces más, y para saber si eso es una tortilla no hace falta."""
    user_id, _ = two_users
    ai_session = await _request(user_id)
    from pathlib import Path

    path = Path(ai_session.request_payload["image_path"])
    try:
        with Image.open(path) as saved:
            assert max(saved.size) <= 1024
            assert saved.format == "JPEG"
            # Reexportar con Pillow deja la imagen sin EXIF: nunca se guardan los bytes
            # originales, que pueden llevar la geolocalización de dónde se comió.
            assert not saved.getexif()
    finally:
        path.unlink(missing_ok=True)


async def test_una_foto_demasiado_grande_se_rechaza(two_users, configured_credential):
    user_id, _ = two_users
    with pytest.raises(AppError) as exc:
        await _request(user_id, image_bytes=b"x" * (10 * 1024 * 1024 + 1))
    assert exc.value.code == "IMAGE_TOO_LARGE"


async def test_un_formato_no_soportado_se_rechaza(two_users, configured_credential):
    user_id, _ = two_users
    with pytest.raises(AppError) as exc:
        await _request(user_id, content_type="image/gif")
    assert exc.value.code == "UNSUPPORTED_IMAGE_TYPE"


async def test_un_fichero_que_no_es_una_imagen_se_rechaza(two_users, configured_credential):
    user_id, _ = two_users
    with pytest.raises(AppError) as exc:
        await _request(user_id, image_bytes=b"esto no es una imagen")
    assert exc.value.code == "INVALID_IMAGE"


async def test_sin_credencial_no_se_encola_nada(two_users):
    user_id, _ = two_users
    with pytest.raises(AppError) as exc:
        await _request(user_id)
    assert exc.value.code == "AI_NOT_CONFIGURED"


# --- procesado ------------------------------------------------------------------------------


async def test_la_foto_se_borra_pase_lo_que_pase(two_users, configured_credential, monkeypatch):
    """Lo que el usuario ha pedido es registrar una comida, no guardar una imagen. Si se
    quedara en disco sería un dato de salud (lo que come alguien) sin ninguna razón."""
    user_id, _ = two_users
    ai_session = await _request(user_id)
    path = Path(ai_session.request_payload["image_path"])
    assert path.exists()

    async def _boom(**kwargs):
        raise AiAgentError("se cayó el proveedor", code="AI_TIMEOUT")

    monkeypatch.setattr(meal_estimate, "run_agent", _boom)
    await flow.process_plate_photo_job(str(ai_session.id))

    assert not path.exists()
    reloaded = await _reload(ai_session.id)
    assert reloaded.status == "failed"
    assert reloaded.validation_errors[0]["code"] == "AI_TIMEOUT"


async def test_una_foto_sin_comida_termina_bien_y_lo_dice(
    two_users, configured_credential, monkeypatch
):
    user_id, _ = two_users
    ai_session = await _request(user_id)

    async def _sees_nothing(**kwargs):
        await kwargs["mcp_tools"][0].handler({"platos": []})
        return AgentResult(text="", input_tokens=500, output_tokens=20)

    monkeypatch.setattr(meal_estimate, "run_agent", _sees_nothing)
    await flow.process_plate_photo_job(str(ai_session.id))

    reloaded = await _reload(ai_session.id)
    assert reloaded.status == "succeeded"
    assert reloaded.response_payload["warning"] == "NO_FOOD_IN_PHOTO"
    assert reloaded.response_payload["proposal"] is None
    assert reloaded.response_payload["items"] == []
    assert reloaded.input_tokens == 500


BOCADILLO = {
    "nombre": "bocadillo de jamón serrano",
    "cantidad": 1,
    "gramos": 150,
    "componentes": [
        {"nombre": "pan", "gramos": 100, "kcal": 260, "proteina_g": 8, "grasa_g": 1,
         "carbos_g": 52},
        {"nombre": "jamón serrano", "gramos": 45, "kcal": 110, "proteina_g": 14, "grasa_g": 6,
         "carbos_g": 0},
        {"nombre": "aceite de oliva", "gramos": 5, "kcal": 45, "proteina_g": 0, "grasa_g": 5,
         "carbos_g": 0},
    ],
}


def _sees(dishes: list[dict], seen: dict | None = None, pregunta: str | None = None):
    async def _fake_run_agent(**kwargs):
        if seen is not None:
            seen.update(kwargs)
        await kwargs["mcp_tools"][0].handler({"platos": dishes, "pregunta": pregunta})
        return AgentResult(text="", input_tokens=900, output_tokens=120)

    return _fake_run_agent


async def test_es_una_sola_llamada_con_la_imagen_y_sale_una_propuesta_de_diario(
    two_users, configured_credential, monkeypatch
):
    """El criterio del registro por texto, con una imagen: el bocadillo es UNA línea, con su
    desglose en gramos, y queda como propuesta que se aprueba entera."""
    user_id, _ = two_users
    ai_session = await _request(user_id, log_date="2026-09-24", meal_type="dinner")
    calls: list[dict] = []
    seen: dict = {}

    async def _counting(**kwargs):
        calls.append(kwargs)
        return await _sees([BOCADILLO], seen, "¿Lleva tomate?")(**kwargs)

    monkeypatch.setattr(meal_estimate, "run_agent", _counting)
    await flow.process_plate_photo_job(str(ai_session.id))

    assert len(calls) == 1  # antes eran dos, y una tercera de búsqueda web
    assert seen["system_prompt"] == PLATE_PHOTO_SYSTEM_V2
    assert [t.name for t in seen["mcp_tools"]] == ["estimate_meal"]
    (media_type, data) = seen["images"][0]
    assert media_type == "image/jpeg" and len(data) > 100

    reloaded = await _reload(ai_session.id)
    assert reloaded.status == "succeeded"
    assert (reloaded.input_tokens, reloaded.output_tokens) == (900, 120)
    response = reloaded.response_payload
    assert response["pregunta"] == "¿Lleva tomate?"
    assert response["visto"] == [BOCADILLO]
    payload = response["proposal"]["payload"]
    assert (payload["date"], payload["meal_type"]) == ("2026-09-24", "dinner")
    (item,) = payload["items"]
    assert item["name"] == "Bocadillo de jamón serrano"
    assert item["estimated"] is True
    assert [(c["name"], c["grams"]) for c in item["components"]] == [
        ("pan", 100), ("jamón serrano", 45), ("aceite de oliva", 5),
    ]
    assert item["kcal"] == 415  # la suma de sus partes
    assert (item["protein_g"], item["fat_g"], item["carbs_g"]) == (22, 12, 52)

    async with AdminSessionLocal() as session:
        stored = await session.get(AiProposal, uuid.UUID(response["proposal"]["ai_proposal_id"]))
    assert stored.scope == "diary" and stored.status == "pending"


async def test_cada_parte_se_afina_con_el_catalogo_y_lo_demas_se_queda_estimado(
    two_users, configured_credential, catalog_bread_and_ham, monkeypatch
):
    """Lo que se pidió: descomponer, buscar cada alimento en el catálogo para afinar calorías
    y nutrientes, y estimar lo que no esté. Los gramos son siempre los del modelo."""
    user_id, _ = two_users
    ai_session = await _request(user_id)
    monkeypatch.setattr(meal_estimate, "run_agent", _sees([BOCADILLO]))
    await flow.process_plate_photo_job(str(ai_session.id))

    (item,) = (await _reload(ai_session.id)).response_payload["proposal"]["payload"]["items"]
    pan, jamon, aceite = item["components"]
    # Confirmados: valores del catálogo para los gramos que vio el modelo.
    assert (pan["grams"], pan["kcal"], pan["catalog"]) == (100, 262, "Pan blanco, de barra")
    assert (jamon["grams"], jamon["kcal"], jamon["catalog"]) == (45, 105.8, "Jamón curado Serrano")
    # No hay aceite en este catálogo de prueba: se queda lo que estimó el modelo.
    assert (aceite["grams"], aceite["kcal"]) == (5, 45) and "catalog" not in aceite
    assert item["kcal"] == round(262 + 105.8 + 45, 1)
    assert item["protein_g"] == round(8.5 + 30.5 * 0.45, 1)
    # Los micronutrientes, que una estimación sola no trae.
    assert item["micros"] == {"calcium_mg": 30, "iron_mg": 1.5 + 2.0 * 0.45}
    assert item["estimated"] is True  # los gramos siguen siendo una estimación


async def test_una_foto_hecha_en_vertical_no_llega_tumbada(two_users, configured_credential):
    """La orientación de una foto de móvil va en el EXIF, que se tira: hay que aplicarla
    antes, o el modelo ve el plato de lado."""
    user_id, _ = two_users
    image = Image.new("RGB", (1600, 1200), (200, 180, 140))
    exif = image.getexif()
    exif[0x0112] = 6  # «girar 90° para verla derecha»
    buf = BytesIO()
    image.save(buf, format="JPEG", exif=exif)

    ai_session = await _request(user_id, image_bytes=buf.getvalue())

    with Image.open(ai_session.request_payload["image_path"]) as stored:
        assert stored.height > stored.width
        assert not stored.getexif()


async def test_un_plato_imposible_falla_con_un_mensaje_claro(
    two_users, configured_credential, monkeypatch
):
    user_id, _ = two_users
    ai_session = await _request(user_id)
    monkeypatch.setattr(
        meal_estimate, "run_agent", _sees([{"nombre": "paella", "gramos": 300, "kcal": 9000}])
    )
    await flow.process_plate_photo_job(str(ai_session.id))

    reloaded = await _reload(ai_session.id)
    assert reloaded.status == "failed"
    assert reloaded.validation_errors[0]["code"] == "IMPLAUSIBLE_ESTIMATE"


async def test_la_sesion_guarda_la_comida_y_el_dia_para_la_pantalla(
    two_users, configured_credential
):
    user_id, _ = two_users
    ai_session = await _request(user_id, log_date="2026-09-20", meal_type="dinner")
    assert ai_session.request_payload["log_date"] == "2026-09-20"
    assert ai_session.request_payload["meal_type"] == "dinner"
    assert ai_session.request_payload["prompt_version"] == "plate_photo_v2"
