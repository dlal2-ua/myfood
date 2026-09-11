import redis.asyncio as redis
from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from myfood.config import get_settings

router = APIRouter(tags=["health"])
settings = get_settings()

VERSION = "0.1.0"


@router.get("/health")
async def health() -> dict:
    status = {"status": "ok", "version": VERSION}

    try:
        engine = create_async_engine(settings.database_url_superuser)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        status["db"] = "ok"
        await engine.dispose()
    except Exception:
        status["db"] = "error"
        status["status"] = "degraded"

    try:
        r = redis.from_url(settings.redis_url)
        await r.ping()
        status["redis"] = "ok"
        await r.aclose()
    except Exception:
        status["redis"] = "error"
        status["status"] = "degraded"

    try:
        import httpx

        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{settings.meili_url}/health")
            status["meili"] = "ok" if resp.status_code == 200 else "error"
            if resp.status_code != 200:
                status["status"] = "degraded"
    except Exception:
        status["meili"] = "error"
        status["status"] = "degraded"

    return status
