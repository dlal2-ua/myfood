"""Cliente de Meilisearch para el buscador de alimentos (sección 7.2, 11.3)."""

import httpx

from myfood.config import get_settings

settings = get_settings()


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.meili_master_key:
        headers["Authorization"] = f"Bearer {settings.meili_master_key}"
    return headers


async def search_foods(
    query: str, kind: str | None, limit: int, offset: int
) -> tuple[list[dict], int]:
    body: dict = {"q": query, "limit": limit, "offset": offset}
    if kind:
        body["filter"] = f"kind = {kind}"

    async with httpx.AsyncClient(
        base_url=settings.meili_url, headers=_headers(), timeout=5
    ) as client:
        resp = await client.post("/indexes/foods/search", json=body)
        resp.raise_for_status()
        data = resp.json()
    return data["hits"], data["estimatedTotalHits"]
