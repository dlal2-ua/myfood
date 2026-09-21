"""Cliente de Meilisearch para el buscador de alimentos (sección 7.2, 11.3)."""

from dataclasses import dataclass, field

import httpx

from myfood.config import get_settings

settings = get_settings()

# Atributos por los que la web ofrece filtros, y con cuántos resultados cuenta cada opción.
FACET_ATTRIBUTES = ("supermarket", "food_group", "nutrition_tags")

SORTS: dict[str, list[str] | None] = {
    "relevance": None,
    "kcal_asc": ["kcal_100g:asc"],
    "protein_desc": ["protein_100g:desc"],
}

# Fuentes con el nombre en inglés (USDA) o francés (CIQUAL), pendientes de traducir: al explorar
# el catálogo sin escribir nada solo se enseña lo que está en español. Si el usuario escribe algo,
# se busca en todo.
NON_SPANISH_SOURCES = ("usda_foundation", "usda_sr", "ciqual")


@dataclass(frozen=True)
class FoodFilters:
    """Filtros elegidos en la web. Dentro de supermercado y de tipo de alimento las opciones se
    suman (Lidl O Aldi); las etiquetas de nutrición se exigen todas (alto en proteína Y bajo en
    grasa). Los valores ya están validados contra la taxonomía: nunca texto libre del usuario."""

    kind: str | None = None
    supermarkets: tuple[str, ...] = ()
    food_types: tuple[str, ...] = ()
    nutrition: tuple[str, ...] = ()

    @property
    def any(self) -> bool:
        return bool(self.kind or self.supermarkets or self.food_types or self.nutrition)


def build_filter(filters: FoodFilters, *, browsing: bool, skip: str | None = None) -> list:
    """Filtro de Meilisearch: lista de condiciones que se cumplen todas; una sublista es un «o».
    `skip` deja fuera el filtro de un atributo (para contar sus opciones sin que su propia
    selección las esconda)."""
    clauses: list = []
    if filters.kind:
        clauses.append(f'kind = "{filters.kind}"')
    if filters.supermarkets and skip != "supermarket":
        clauses.append([f'supermarket = "{v}"' for v in filters.supermarkets])
    if filters.food_types and skip != "food_group":
        clauses.append([f'food_group = "{v}"' for v in filters.food_types])
    if skip != "nutrition_tags":
        clauses.extend(f'nutrition_tags = "{v}"' for v in filters.nutrition)
    if browsing:
        clauses.extend(f'source != "{source}"' for source in NON_SPANISH_SOURCES)
    return clauses


@dataclass
class SearchResult:
    hits: list[dict]
    total: int
    # atributo -> valor -> número de alimentos; vacío si no se pidieron facetas.
    facets: dict[str, dict[str, int]] = field(default_factory=dict)


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.meili_master_key:
        headers["Authorization"] = f"Bearer {settings.meili_master_key}"
    return headers


async def search_foods_filtered(
    query: str,
    filters: FoodFilters,
    *,
    sort: str = "relevance",
    limit: int = 20,
    offset: int = 0,
    with_facets: bool = False,
) -> SearchResult:
    browsing = not query.strip()
    main: dict = {"indexUid": settings.meili_index, "q": query, "limit": limit, "offset": offset}
    if clauses := build_filter(filters, browsing=browsing):
        main["filter"] = clauses
    sort_rule = SORTS[sort]
    if sort_rule is None and browsing:
        sort_rule = ["quality_rank:asc"]  # sin texto, primero lo que tiene dato oficial
    if sort_rule:
        main["sort"] = sort_rule

    async with httpx.AsyncClient(
        base_url=settings.meili_url, headers=_headers(), timeout=5
    ) as client:
        if not with_facets:
            body = {k: v for k, v in main.items() if k != "indexUid"}
            resp = await client.post(f"/indexes/{settings.meili_index}/search", json=body)
            resp.raise_for_status()
            data = resp.json()
            return SearchResult(data["hits"], data["estimatedTotalHits"])

        # Una consulta por atributo para contar sus opciones «como si» aquel filtro no estuviera.
        queries = [main]
        for attribute in FACET_ATTRIBUTES:
            counting: dict = {
                "indexUid": settings.meili_index,
                "q": query,
                "limit": 0,
                "facets": [attribute],
            }
            if clauses := build_filter(filters, browsing=browsing, skip=attribute):
                counting["filter"] = clauses
            queries.append(counting)
        resp = await client.post("/multi-search", json={"queries": queries})
        resp.raise_for_status()
        results = resp.json()["results"]

    facets = {
        attribute: results[i + 1].get("facetDistribution", {}).get(attribute, {})
        for i, attribute in enumerate(FACET_ATTRIBUTES)
    }
    return SearchResult(results[0]["hits"], results[0]["estimatedTotalHits"], facets)


async def search_foods(
    query: str, kind: str | None, limit: int, offset: int
) -> tuple[list[dict], int]:
    result = await search_foods_filtered(
        query, FoodFilters(kind=kind), limit=limit, offset=offset
    )
    return result.hits, result.total
