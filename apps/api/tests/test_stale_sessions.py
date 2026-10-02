"""Barrendero de sesiones de iafood huérfanas (`worker.fail_stale_sessions`)."""

import os
from datetime import UTC, datetime, timedelta

import pytest

from myfood.db.models import AiSession
from myfood.db.session import AdminSessionLocal
from myfood.worker import fail_stale_sessions, purge_orphan_uploads

pytestmark = pytest.mark.asyncio


async def _make(user_id, *, minutes_old: int, status: str = "running") -> AiSession:
    async with AdminSessionLocal() as session:
        ai_session = AiSession(
            user_id=user_id,
            kind="chat_edit",
            status=status,
            request_payload={"source": "text", "text": "hola"},
            created_at=datetime.now(UTC) - timedelta(minutes=minutes_old),
        )
        session.add(ai_session)
        await session.commit()
        await session.refresh(ai_session)
        return ai_session


async def _reload(session_id) -> AiSession:
    async with AdminSessionLocal() as session:
        return await session.get(AiSession, session_id)


async def test_old_running_session_is_marked_failed_with_a_clear_code(two_users):
    user_id, _ = two_users
    stale = await _make(user_id, minutes_old=30)

    await fail_stale_sessions()

    reloaded = await _reload(stale.id)
    assert reloaded.status == "failed"
    assert reloaded.validation_errors[0]["code"] == "SESSION_ORPHANED"


async def test_recent_running_session_is_left_alone(two_users):
    user_id, _ = two_users
    recent = await _make(user_id, minutes_old=1)

    await fail_stale_sessions()

    assert (await _reload(recent.id)).status == "running"


async def test_finished_sessions_are_never_touched(two_users):
    user_id, _ = two_users
    done = await _make(user_id, minutes_old=60, status="succeeded")

    await fail_stale_sessions()

    reloaded = await _reload(done.id)
    assert reloaded.status == "succeeded"
    assert reloaded.validation_errors is None


def test_a_photo_that_outlived_its_job_is_deleted(tmp_path):
    """Si el worker se reinicia a mitad de un análisis, el `finally` que borra la foto no
    corre. Se encontró una en producción cinco días después de subirla."""
    now = datetime.now(UTC)
    old = (now - timedelta(minutes=30)).timestamp()
    plates, receipts, user = tmp_path / "plates", tmp_path / "receipts", tmp_path / "user"
    for folder in (plates, receipts, user):
        folder.mkdir()
    orphan_plate = plates / "huerfana.jpg"
    orphan_receipt = receipts / "ticket.jpg"
    in_progress = plates / "analizandose.jpg"
    avatar = user / "foto-de-perfil.jpg"
    for path in (orphan_plate, orphan_receipt, in_progress, avatar):
        path.write_bytes(b"jpg")
    for path in (orphan_plate, orphan_receipt, avatar):
        os.utime(path, (old, old))

    assert purge_orphan_uploads(now, root=tmp_path) == 2

    assert not orphan_plate.exists() and not orphan_receipt.exists()
    # La que se está analizando ahora mismo no se toca, ni nada fuera de esas dos carpetas.
    assert in_progress.exists()
    assert avatar.exists()


def test_purging_without_the_folders_is_not_an_error(tmp_path):
    assert purge_orphan_uploads(root=tmp_path) == 0
