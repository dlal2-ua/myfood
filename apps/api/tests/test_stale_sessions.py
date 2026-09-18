"""Barrendero de sesiones de iafood huérfanas (`worker.fail_stale_sessions`)."""

from datetime import UTC, datetime, timedelta

import pytest

from myfood.db.models import AiSession
from myfood.db.session import AdminSessionLocal
from myfood.worker import fail_stale_sessions

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
