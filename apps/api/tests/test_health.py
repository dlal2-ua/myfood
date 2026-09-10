import pytest
from httpx import ASGITransport, AsyncClient

from myfood.main import app


@pytest.mark.asyncio
async def test_health_ok():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["db"] == "ok"
    assert body["redis"] == "ok"
    assert body["meili"] == "ok"
    assert body["status"] == "ok"
