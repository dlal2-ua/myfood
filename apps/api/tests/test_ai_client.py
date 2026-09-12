import pytest_asyncio
from sqlalchemy import text

from myfood.ai import client as ai_client
from myfood.db.session import AdminSessionLocal


@pytest_asyncio.fixture
async def clean_ai_credential(superuser_conn):
    await superuser_conn.execute(text("DELETE FROM ai_credentials"))
    await superuser_conn.commit()
    yield
    await superuser_conn.execute(text("DELETE FROM ai_credentials"))
    await superuser_conn.commit()


async def test_credential_starts_unconfigured(clean_ai_credential):
    async with AdminSessionLocal() as session:
        status = await ai_client.get_credential_status(session)
    assert status.configured is False
    assert status.provider is None
    assert status.updated_at is None


async def test_set_and_get_credential_round_trip(two_users, clean_ai_credential):
    admin_id, _ = two_users
    async with AdminSessionLocal() as session:
        await ai_client.set_credential(
            session, admin_user_id=admin_id, token="sk-ant-oat-test-token"
        )
    async with AdminSessionLocal() as session:
        status = await ai_client.get_credential_status(session)
        assert status.configured is True
        assert status.provider == "anthropic"
        assert status.updated_at is not None
        decrypted = await ai_client.get_decrypted_token(session)
        assert decrypted == "sk-ant-oat-test-token"


async def test_credential_is_encrypted_at_rest(two_users, clean_ai_credential, superuser_conn):
    admin_id, _ = two_users
    token = "sk-ant-oat-super-secret-value"
    async with AdminSessionLocal() as session:
        await ai_client.set_credential(session, admin_user_id=admin_id, token=token)

    row = (
        await superuser_conn.execute(
            text("SELECT token_encrypted FROM ai_credentials WHERE id = 1")
        )
    ).one()
    raw_bytes = bytes(row[0])
    assert token.encode("utf-8") not in raw_bytes


async def test_set_credential_overwrites_previous_value(two_users, clean_ai_credential):
    admin_a, admin_b = two_users
    async with AdminSessionLocal() as session:
        await ai_client.set_credential(session, admin_user_id=admin_a, token="first-token")
    async with AdminSessionLocal() as session:
        await ai_client.set_credential(session, admin_user_id=admin_b, token="second-token")
    async with AdminSessionLocal() as session:
        decrypted = await ai_client.get_decrypted_token(session)
        assert decrypted == "second-token"


async def test_get_decrypted_token_is_none_when_unconfigured(clean_ai_credential):
    async with AdminSessionLocal() as session:
        assert await ai_client.get_decrypted_token(session) is None
