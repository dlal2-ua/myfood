"""Tests del flujo de escaneo OCR de tickets de compra (Fase 7).

`process_receipt_scan_job` se prueba sin Tesseract real: `extract_lines`
se simula devolviendo líneas de texto fijas (mismo criterio que
`test_recipe_import_flow.py` simulando `_fetch_html` — depender del OCR
real habría hecho estos tests frágiles por motivos ajenos al código, y
Tesseract no está instalado en el entorno de CI). La resolución de cada
línea se simula igual que en `test_recipe_import_flow.py`, porque reutiliza
el mismo `ai/flows/food_resolution.py`."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from myfood.ai import client as ai_client
from myfood.ai.agent import AgentResult
from myfood.ai.flows import food_resolution
from myfood.ai.flows import receipt_scan as flow
from myfood.db.models import AiSession
from myfood.db.session import AdminSessionLocal
from myfood.errors import AppError

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def one_real_food(superuser_conn):
    food_id = uuid.uuid4()
    await superuser_conn.execute(
        text(
            "INSERT INTO foods "
            "(id, kind, source, source_id, license, name_es, quality_rank, serving_size_g) "
            "VALUES (:id, 'generic', 'test', :sid, 'CC0', 'Leche entera (test)', 1, 200)"
        ),
        {"id": str(food_id), "sid": str(food_id)},
    )
    await superuser_conn.execute(
        text(
            "INSERT INTO food_nutrients "
            "(food_id, kcal_100g, protein_100g, fat_100g, carbs_100g, micros) "
            "VALUES (:id, 61, 3.2, 3.3, 4.8, '{}'::jsonb)"
        ),
        {"id": str(food_id)},
    )
    await superuser_conn.commit()
    yield str(food_id)
    await superuser_conn.execute(text("DELETE FROM foods WHERE id = :id"), {"id": str(food_id)})
    await superuser_conn.commit()


@pytest_asyncio.fixture
async def configured_credential(two_users):
    admin_id, _ = two_users
    async with AdminSessionLocal() as session:
        await ai_client.set_credential(session, admin_user_id=admin_id, token="fake-test-token")
    yield
    async with AdminSessionLocal() as session:
        await session.execute(text("DELETE FROM ai_credentials"))
        await session.commit()


@pytest_asyncio.fixture
async def running_receipt_scan_session(two_users, tmp_path):
    user_id, _ = two_users
    image_path = tmp_path / "receipt.jpg"
    image_path.write_bytes(b"not a real image, extract_lines is mocked in these tests")

    async with AdminSessionLocal() as session:
        ai_session = AiSession(
            user_id=user_id,
            kind="receipt_scan",
            status="running",
            request_payload={
                "prompt_version": "receipt_scan_v1",
                "image_path": str(image_path),
            },
        )
        session.add(ai_session)
        await session.commit()
        await session.refresh(ai_session)
    return ai_session.id


async def _reload(session_id) -> AiSession:
    async with AdminSessionLocal() as session:
        return await session.get(AiSession, session_id)


def _fake_agent_call(items: list[dict]):
    async def _fake_run_agent(
        *, token, prompt, system_prompt, mcp_tools, max_turns, timeout_seconds
    ):
        await mcp_tools[0].handler({"items": items})
        return AgentResult(text="", input_tokens=3, output_tokens=2)

    return _fake_run_agent


def _fake_search_foods_always_hits(food_id: str, name: str):
    async def _fake(query, kind, limit, offset):
        return [{"id": food_id, "name_es": name, "category": None}], 1

    return _fake


async def test_success_path_resolves_food_lines_and_skips_noise(
    running_receipt_scan_session, one_real_food, configured_credential, monkeypatch
):
    monkeypatch.setattr(
        flow, "extract_lines", lambda image_bytes: ["Leche entera 1L", "TOTAL 5,43 EUR"]
    )

    async def _fake_search_foods(query, kind, limit, offset):
        if "leche" in query.lower() or "Leche" in query:
            return [{"id": one_real_food, "name_es": "Leche entera (test)", "category": None}], 1
        return [], 0

    monkeypatch.setattr(food_resolution, "search_foods", _fake_search_foods)
    monkeypatch.setattr(
        food_resolution,
        "run_agent",
        _fake_agent_call([{"alias": "c1", "approx_quantity_text": "1L"}]),
    )

    await flow.process_receipt_scan_job(str(running_receipt_scan_session))

    ai_session = await _reload(running_receipt_scan_session)
    assert ai_session.status == "succeeded"
    payload = ai_session.response_payload
    assert payload["lines_found"] == 2
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["food_id"] == one_real_food
    assert item["original_line"] == "Leche entera 1L"
    # El "TOTAL 5,43 EUR" no tiene candidatos (mock devuelve [] para él) —
    # se descarta sin más, tal y como se pide en el prompt.


async def test_image_file_is_deleted_after_processing(
    running_receipt_scan_session, one_real_food, configured_credential, monkeypatch
):
    monkeypatch.setattr(flow, "extract_lines", lambda image_bytes: ["Leche entera 1L"])
    monkeypatch.setattr(
        food_resolution, "search_foods", _fake_search_foods_always_hits(one_real_food, "Leche")
    )
    monkeypatch.setattr(
        food_resolution,
        "run_agent",
        _fake_agent_call([{"alias": "c1", "approx_quantity_text": "1L"}]),
    )

    ai_session = await _reload(running_receipt_scan_session)
    from pathlib import Path

    image_path = Path(ai_session.request_payload["image_path"])
    assert image_path.exists()

    await flow.process_receipt_scan_job(str(running_receipt_scan_session))

    assert not image_path.exists()


async def test_no_text_found_marks_session_failed(
    running_receipt_scan_session, configured_credential, monkeypatch
):
    monkeypatch.setattr(flow, "extract_lines", lambda image_bytes: [])

    await flow.process_receipt_scan_job(str(running_receipt_scan_session))

    ai_session = await _reload(running_receipt_scan_session)
    assert ai_session.status == "failed"
    assert ai_session.validation_errors[0]["code"] == "NO_TEXT_FOUND"


async def test_missing_image_marks_session_failed(
    running_receipt_scan_session, configured_credential
):
    ai_session = await _reload(running_receipt_scan_session)
    from pathlib import Path

    Path(ai_session.request_payload["image_path"]).unlink()

    await flow.process_receipt_scan_job(str(running_receipt_scan_session))

    ai_session = await _reload(running_receipt_scan_session)
    assert ai_session.status == "failed"
    assert ai_session.validation_errors[0]["code"] == "IMAGE_NOT_FOUND"


async def test_no_credential_marks_session_failed(running_receipt_scan_session, monkeypatch):
    monkeypatch.setattr(flow, "extract_lines", lambda image_bytes: ["Leche entera 1L"])

    await flow.process_receipt_scan_job(str(running_receipt_scan_session))

    ai_session = await _reload(running_receipt_scan_session)
    assert ai_session.status == "failed"
    assert ai_session.validation_errors[0]["code"] == "AI_NOT_CONFIGURED"


async def test_already_processed_session_is_a_noop(running_receipt_scan_session):
    async with AdminSessionLocal() as session:
        ai_session = await session.get(AiSession, running_receipt_scan_session)
        ai_session.status = "succeeded"
        ai_session.response_payload = {"items": [], "lines_found": 0}
        await session.commit()

    # No debe reventar ni volver a procesar (idempotencia defensiva).
    await flow.process_receipt_scan_job(str(running_receipt_scan_session))

    ai_session = await _reload(running_receipt_scan_session)
    assert ai_session.status == "succeeded"


# --- request_receipt_scan (api) ----------------------------------------------


def _tiny_jpeg_bytes() -> bytes:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (10, 10), color="white").save(buf, format="JPEG")
    return buf.getvalue()


async def test_request_raises_ai_not_configured_without_credential(two_users):
    user_id, _ = two_users
    async with AdminSessionLocal() as session:
        await session.execute(text("DELETE FROM ai_credentials"))
        await session.commit()
        with pytest.raises(AppError) as exc_info:
            await flow.request_receipt_scan(
                session, user_id, image_bytes=_tiny_jpeg_bytes(), content_type="image/jpeg"
            )
        assert exc_info.value.code == "AI_NOT_CONFIGURED"


async def test_request_rejects_oversized_image(two_users, configured_credential):
    user_id, _ = two_users
    oversized = b"x" * (9 * 1024 * 1024)
    async with AdminSessionLocal() as session:
        with pytest.raises(AppError) as exc_info:
            await flow.request_receipt_scan(
                session, user_id, image_bytes=oversized, content_type="image/jpeg"
            )
        assert exc_info.value.code == "IMAGE_TOO_LARGE"


async def test_request_rejects_unsupported_content_type(two_users, configured_credential):
    user_id, _ = two_users
    async with AdminSessionLocal() as session:
        with pytest.raises(AppError) as exc_info:
            await flow.request_receipt_scan(
                session, user_id, image_bytes=_tiny_jpeg_bytes(), content_type="application/pdf"
            )
        assert exc_info.value.code == "UNSUPPORTED_IMAGE_TYPE"


async def test_request_creates_running_session_saves_image_and_enqueues(
    two_users, configured_credential, monkeypatch, tmp_path
):
    from pathlib import Path

    user_id, _ = two_users
    enqueued = []

    async def _fake_enqueue(ai_session_id: str) -> None:
        enqueued.append(ai_session_id)

    monkeypatch.setattr(flow, "enqueue_receipt_scan_job", _fake_enqueue)
    monkeypatch.setattr(flow, "_RECEIPTS_DIR", tmp_path / "receipts")

    async with AdminSessionLocal() as session:
        ai_session = await flow.request_receipt_scan(
            session, user_id, image_bytes=_tiny_jpeg_bytes(), content_type="image/jpeg"
        )

    assert ai_session.status == "running"
    assert ai_session.kind == "receipt_scan"
    image_path = Path(ai_session.request_payload["image_path"])
    assert image_path.exists()
    assert enqueued == [str(ai_session.id)]

    image_path.unlink()
