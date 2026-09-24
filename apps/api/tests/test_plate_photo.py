"""Registro por foto del plato (`ai/flows/plate_photo.py`).

La llamada real al modelo se simula: lo que hay que probar aquí es que la foto se normaliza y
se borra, que la visión no puede colar gramos, y que la segunda fase pasa por el mismo resolutor
que el registro por texto. Que el modelo *vea* de verdad se comprueba en vivo, no en un test.
"""

from io import BytesIO

import pytest
import pytest_asyncio
from PIL import Image
from sqlalchemy import text

from myfood.ai import client as ai_client
from myfood.ai.agent import AgentResult, AiAgentError
from myfood.ai.flows import plate_photo as flow
from myfood.db.models import AiSession
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
    from pathlib import Path

    path = Path(ai_session.request_payload["image_path"])
    assert path.exists()

    async def _boom(**kwargs):
        raise AiAgentError("se cayó el proveedor", code="AI_TIMEOUT")

    monkeypatch.setattr(flow, "run_agent", _boom)
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
        return AgentResult(text="", input_tokens=500, output_tokens=20)

    monkeypatch.setattr(flow, "run_agent", _sees_nothing)
    await flow.process_plate_photo_job(str(ai_session.id))

    reloaded = await _reload(ai_session.id)
    assert reloaded.status == "succeeded"
    assert reloaded.response_payload["warning"] == "NO_FOOD_IN_PHOTO"
    assert reloaded.response_payload["items"] == []
    assert reloaded.input_tokens == 500


async def test_la_vision_manda_la_imagen_y_nunca_devuelve_gramos(
    two_users, configured_credential, monkeypatch
):
    """La herramienta de visión no tiene ningún campo de gramos ni de kcal a propósito (R1):
    describe en medidas de casa y el backend hace la cuenta."""
    user_id, _ = two_users
    ai_session = await _request(user_id)
    recibido = {}

    async def _fake_run_agent(**kwargs):
        recibido.update(kwargs)
        # La herramienta escribe en el sink, igual que en producción.
        for tool_obj in kwargs.get("mcp_tools") or []:
            await tool_obj.handler(
                {"alimentos": [{"nombre": "tortilla de patatas", "cantidad": 1,
                                "tipo_cantidad": "porcion", "origen": "casero"}]}
            )
        return AgentResult(text="", input_tokens=900, output_tokens=60)

    async def _no_candidates(_text):
        return []

    monkeypatch.setattr(flow, "run_agent", _fake_run_agent)
    monkeypatch.setattr(flow, "search_candidates_for_text", _no_candidates)
    await flow.process_plate_photo_job(str(ai_session.id))

    assert recibido["images"], "la foto tiene que viajar como bloque de imagen"
    media_type, data = recibido["images"][0]
    assert media_type == "image/jpeg" and len(data) > 100
    # El esquema no tiene NINGÚN campo donde meter un número nutricional (R1): «gramos» solo
    # aparece como una de las unidades posibles, para cuando se fotografía una báscula.
    campos = set(
        recibido["mcp_tools"][0]
        .input_schema["properties"]["alimentos"]["items"]["properties"]
    )
    assert campos.isdisjoint(
        {"gramos", "grams", "peso", "kcal", "calorias", "proteina", "grasa", "carbohidratos"}
    )

    reloaded = await _reload(ai_session.id)
    assert reloaded.status == "succeeded"
    # Sin candidatos, se dice lo que se vio en vez de callarse.
    assert reloaded.response_payload["no_encontrados"] == ["tortilla de patatas"]
    assert reloaded.response_payload["visto"][0]["origen"] == "casero"


async def test_la_sesion_guarda_la_comida_y_el_dia_para_la_pantalla(
    two_users, configured_credential
):
    user_id, _ = two_users
    ai_session = await _request(user_id, log_date="2026-09-20", meal_type="dinner")
    from pathlib import Path

    try:
        assert ai_session.kind == "plate_photo"
        assert ai_session.request_payload["log_date"] == "2026-09-20"
        assert ai_session.request_payload["meal_type"] == "dinner"
    finally:
        Path(ai_session.request_payload["image_path"]).unlink(missing_ok=True)


async def test_las_coletillas_del_modelo_no_se_buscan(
    two_users, configured_credential, monkeypatch
):
    """Meilisearch exige que TODOS los términos estén en el documento, así que «arroz blanco
    (forma clara redonda)» no encuentra nada y el alimento se pierde. El prompt pide que no las
    use; esto es la red por si las usa igualmente."""
    user_id, _ = two_users
    ai_session = await _request(user_id)
    buscado = {}

    async def _sees(**kwargs):
        for tool_obj in kwargs.get("mcp_tools") or []:
            await tool_obj.handler(
                {
                    "alimentos": [
                        {"nombre": "arroz blanco (forma clara redonda)", "cantidad": 1,
                         "tipo_cantidad": "porcion"}
                    ]
                }
            )
        return AgentResult(text="", input_tokens=1, output_tokens=1)

    async def _capture(texto):
        buscado["texto"] = texto
        return []

    monkeypatch.setattr(flow, "run_agent", _sees)
    monkeypatch.setattr(flow, "search_candidates_for_text", _capture)
    await flow.process_plate_photo_job(str(ai_session.id))

    assert buscado["texto"] == "arroz blanco"


async def test_sin_nada_en_el_catalogo_se_intenta_el_respaldo_web(
    two_users, configured_credential, monkeypatch
):
    """Que el catálogo no tenga NADA de lo que hay en el plato es justo cuando más falta hace
    el respaldo: antes se salía antes de llegar a buscarlo."""
    user_id, _ = two_users
    ai_session = await _request(user_id)
    pedido = {}

    async def _sees(**kwargs):
        for tool_obj in kwargs.get("mcp_tools") or []:
            await tool_obj.handler(
                {"alimentos": [{"nombre": "pastel de cabracho", "cantidad": 1,
                                "tipo_cantidad": "racion"}]}
            )
        return AgentResult(text="", input_tokens=1, output_tokens=1)

    async def _nothing(_texto):
        return []

    async def _fake_fallback(session, **kwargs):
        pedido.update(kwargs)
        return None, None

    monkeypatch.setattr(flow, "run_agent", _sees)
    monkeypatch.setattr(flow, "search_candidates_for_text", _nothing)
    monkeypatch.setattr(flow, "estimate_missing_foods", _fake_fallback)
    await flow.process_plate_photo_job(str(ai_session.id))

    assert pedido["missing"] == ["pastel de cabracho"]
    assert pedido["meal_type"] == "lunch"
