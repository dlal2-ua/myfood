"""Open Food Facts — España (documento 2, sección 11).

Descarga el dump JSONL completo (público, ~13 GB comprimido) y lo filtra
con DuckDB por `countries_tags` antes de cargar nada — nunca se carga el
fichero entero en memoria ni en Postgres (sección 11.2).

Además de `load()` (dump completo filtrado por país), `load_by_brand()`
consulta la Search API v2 pública de OFF filtrando por `brands_tags` +
`countries_tags_en` — ver docstring de `load_by_brand` para la razón: el
dump filtrado solo por país incluye una cola enorme de entradas de solo
código de barras sin nutrientes, mientras que las marcas de supermercado
más consultadas/editadas por la comunidad están mucho mejor rellenadas.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import duckdb
import httpx

from etl.db import (
    LoadStats,
    ParsedFood,
    get_connection,
    replace_allergens,
    upsert_foods,
    upsert_images,
)
from etl.rejected import Rejection, log_rejections
from etl.transform.allergens import off_tags_to_codes
from etl.transform.nutrient_map import OFF_MACRO_KEYS, OFF_MICRO_KEYS

DUMP_URL = "https://static.openfoodfacts.org/data/openfoodfacts-products.jsonl.gz"
SEARCH_API_URL = "https://world.openfoodfacts.org/api/v2/search"
USER_AGENT = "MyFood-ETL/1.0 (+https://github.com/dlal2-ua/myfood; dev@example.com)"
QUALITY_RANK = 5
CACHE_DIR = Path(__file__).parent.parent / ".cache"

# Marcas de supermercado/distribución con presencia fuerte en España.
# Verificado el 2026-09-11 vía la Search API (ver etl/README.md): estas
# marcas concentran productos activamente mantenidos por la comunidad,
# muy por encima de la tasa de completitud del dump filtrado solo por país.
DEFAULT_TARGET_BRANDS: tuple[str, ...] = (
    "hacendado",
    "carrefour",
    "lidl",
    "aldi",
    "dia",
    "consum",
    "eroski",
    "alcampo",
    "auchan",
    "condis",
    "bonpreu",
    "el-corte-ingles",
    "mercadona",
    "froiz",
    "spar",
    # Caprabo, Gadis, Ahorramás y Masymas se retiraron a petición del usuario: ya no se
    # etiquetan como supermercado, así que tampoco se incorporan productos nuevos suyos.
    "hipercor",
)

_API_FIELDS = (
    "code,product_name,product_name_es,brands,categories_tags,quantity,"
    "serving_size,serving_quantity,nutriscore_grade,nova_group,ecoscore_grade,nutriments"
)

_DUCKDB_COLUMNS = {
    "code": "VARCHAR",
    "product_name": "VARCHAR",
    "product_name_es": "VARCHAR",
    "brands": "VARCHAR",
    "categories_tags": "VARCHAR[]",
    "quantity": "VARCHAR",
    "serving_size": "VARCHAR",
    "serving_quantity": "DOUBLE",
    "nutriscore_grade": "VARCHAR",
    "nova_group": "INTEGER",
    "ecoscore_grade": "VARCHAR",
    "countries_tags": "VARCHAR[]",
    "brands_tags": "VARCHAR[]",
    "nutriments": "JSON",
}


def download(cache_dir: Path = CACHE_DIR) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "off-products.jsonl.gz"
    if not path.exists():
        with httpx.stream(
            "GET",
            DUMP_URL,
            headers={"User-Agent": "MyFood/1.0 (dev@example.com)"},
            timeout=None,
            follow_redirects=True,
        ) as resp:
            resp.raise_for_status()
            with path.open("wb") as f:
                for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                    f.write(chunk)
    return path


def filter_spain(dump_path: Path, output_path: Path, country: str = "en:spain") -> int:
    """Filtra el dump completo con DuckDB, sin cargarlo en memoria (sección 11.2).

    Investigado el 2026-09-11: un producto con `nutriments` vacío al filtrar
    parecía un bug de DuckDB (el mismo código, vía la API pública de OFF,
    devuelve nutrientes completos). Verificado leyendo la línea cruda del
    dump directamente con `gzip`/`json` de la librería estándar, sin DuckDB
    de por medio: el dump estático **no tiene** `nutriments` para ese
    producto — su `last_modified_t` es posterior a la generación del dump.
    No es un bug de lectura, es la desincronización normal entre el dump
    diario y los datos en vivo (esperable, no evitable). DuckDB lee el
    fichero correctamente tal cual está.
    """
    columns_sql = ", ".join(f"'{k}': '{v}'" for k, v in _DUCKDB_COLUMNS.items())
    query = f"""
    COPY (
        SELECT code, product_name, product_name_es, brands, quantity,
               serving_size, serving_quantity, nutriscore_grade, nova_group,
               ecoscore_grade, categories_tags, nutriments
        FROM read_ndjson(
            '{dump_path}',
            columns={{{columns_sql}}},
            ignore_errors=true
        )
        WHERE list_contains(countries_tags, '{country}')
    ) TO '{output_path}' (FORMAT JSON)
    """
    con = duckdb.connect()
    con.execute(query)
    con.close()

    with output_path.open(encoding="utf-8") as f:
        return sum(1 for _ in f)


def filter_brands(
    dump_path: Path, output_path: Path, brands: Sequence[str], country: str = "en:spain"
) -> int:
    """Filtra el dump completo por marca + país, con DuckDB (sección 11.2).

    Alternativa a `filter_spain()` (que solo filtra por país): investigado el
    2026-09-11 que filtrar solo por país deja pasar una cola enorme de altas
    de solo código de barras sin nutrientes (94,7% del total, ver
    `etl/README.md`). Restringir además a marcas de supermercado con mucho
    tráfico de escaneo/edición comunitaria da una tasa de completitud mucho
    mejor — confirmado contra la Search API pública antes de escribir esto
    (`brands_tags=hacendado&countries_tags_en=spain` da 10.807 resultados con
    nutrientes reales), pero esa misma API pública limita la paginación
    anónima a los primeros 1.000 resultados por consulta (confirmado en la
    práctica: 401/503 exactamente en la página 11 con `page_size=100`, y
    solo en marcas cuyo `count` supera 1.000). Filtrar el dump local con
    DuckDB no tiene ese límite — es un fichero local, no una API paginada.

    Cada nombre en `brands` se compara en minúsculas contra cada elemento de
    `brands_tags`. Los tags vienen con el prefijo de idioma `xx:` (etiqueta
    "sin idioma", igual convención que usa OFF para tags que no se traducen
    — verificado contra el dump crudo el 2026-09-11: el primer campo `curl`
    a la API en vivo de un producto real devolvía `"hacendado"` sin prefijo,
    pero el propio fichero del dump trae `"xx:hacendado"`. Confirmado leyendo
    la línea cruda del dump con `zgrep`/`json` de la librería estándar, sin
    DuckDB de por medio — el mismo patrón de verificación bypass-la-capa-
    sospechosa que ya se usó para depurar `filter_spain` (ver docstring de
    esa función). Comparar sin el prefijo daba 0 resultados en la carga
    real — no es un caso hipotético, se detectó así.
    """
    for brand in brands:
        if not brand.replace("-", "").isalnum():
            raise ValueError(f"nombre de marca inesperado, no se interpola en SQL: {brand!r}")

    brand_conditions = " OR ".join(
        f"list_contains(list_transform(brands_tags, x -> lower(x)), 'xx:{b.lower()}')"
        for b in brands
    )
    columns_sql = ", ".join(f"'{k}': '{v}'" for k, v in _DUCKDB_COLUMNS.items())
    query = f"""
    COPY (
        SELECT code, product_name, product_name_es, brands, quantity,
               serving_size, serving_quantity, nutriscore_grade, nova_group,
               ecoscore_grade, categories_tags, nutriments
        FROM read_ndjson(
            '{dump_path}',
            columns={{{columns_sql}}},
            ignore_errors=true
        )
        WHERE list_contains(countries_tags, '{country}') AND ({brand_conditions})
    ) TO '{output_path}' (FORMAT JSON)
    """
    con = duckdb.connect()
    con.execute(query)
    con.close()

    with output_path.open(encoding="utf-8") as f:
        return sum(1 for _ in f)


_VALID_GRADES = {"a", "b", "c", "d", "e"}


def _grade(value: str | None) -> str | None:
    """Nutri-Score/Eco-Score son CHAR(1) a-e — OFF también usa 'unknown',
    'not-applicable' u otros valores no puntuables; se descartan sin más
    (nunca se inventa una nota), nunca se pasan tal cual a la BD."""
    if value is None:
        return None
    value = value.strip().lower()
    return value if value in _VALID_GRADES else None


def _nova(value) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= 4 else None


def _first_category(categories_tags: list | None) -> str | None:
    if not categories_tags:
        return None
    # 'en:dairies' -> 'dairies'
    return categories_tags[-1].split(":", 1)[-1].replace("-", " ")


def _per_100g(nutriments: dict, key: str, serving_quantity: float | None) -> float | None:
    value_100g = nutriments.get(f"{key}_100g")
    if value_100g is not None:
        return value_100g
    value_serving = nutriments.get(f"{key}_serving")
    if value_serving is not None and serving_quantity:
        return value_serving * 100 / serving_quantity
    return None


def parse_food(raw: dict) -> ParsedFood | Rejection:
    """Transforma un registro crudo de OFF. Función pura — sin I/O (testeable)."""
    barcode = str(raw.get("code") or "").strip()
    name = (raw.get("product_name_es") or raw.get("product_name") or "").strip()
    if not barcode:
        return Rejection("off", None, name or None, "MISSING_BARCODE")
    if not name:
        return Rejection("off", barcode, None, "MISSING_NAME")

    nutriments = raw.get("nutriments") or {}
    serving_quantity = raw.get("serving_quantity")

    macros = {}
    for off_key, field_name in OFF_MACRO_KEYS.items():
        base_key = off_key.removesuffix("_100g")
        value = _per_100g(nutriments, base_key, serving_quantity)
        if value is not None:
            macros[field_name] = value

    kcal_100g = macros.get("kcal_100g")
    if kcal_100g is None:
        return Rejection("off", barcode, name, "MISSING_KCAL")
    if kcal_100g > 900:
        return Rejection("off", barcode, name, "KCAL_OUT_OF_RANGE")

    protein = macros.get("protein_100g", 0.0)
    fat = macros.get("fat_100g", 0.0)
    carbs = macros.get("carbs_100g", 0.0)
    if protein + fat + carbs > 100:
        return Rejection("off", barcode, name, "MACROS_EXCEED_100G")

    micros = {}
    for off_key, key in OFF_MICRO_KEYS.items():
        base_key = off_key.removesuffix("_100g")
        value = _per_100g(nutriments, base_key, serving_quantity)
        if value is not None:
            micros[key] = value

    return ParsedFood(
        source="off",
        source_id=barcode,
        license="ODbL",
        attribution="Open Food Facts",
        kind="branded",
        barcode_ean=barcode,
        name_es=name,
        name_en=raw.get("product_name") if raw.get("product_name") != name else None,
        brand=raw.get("brands"),
        category=_first_category(raw.get("categories_tags")),
        serving_size_g=serving_quantity,
        serving_label=raw.get("serving_size"),
        quality_rank=QUALITY_RANK,
        nutriscore_grade=_grade(raw.get("nutriscore_grade")),
        nova_group=_nova(raw.get("nova_group")),
        ecoscore_grade=_grade(raw.get("ecoscore_grade")),
        kcal_100g=kcal_100g,
        protein_100g=protein,
        fat_100g=fat,
        saturated_100g=macros.get("saturated_100g"),
        carbs_100g=carbs,
        sugars_100g=macros.get("sugars_100g"),
        fiber_100g=macros.get("fiber_100g"),
        salt_100g=macros.get("salt_100g"),
        micros=micros,
    )


@dataclass
class OffLoadResult:
    stats: LoadStats
    rejected_path: Path | None


def load(dump_path: Path | None = None, filtered_path: Path | None = None) -> OffLoadResult:
    filtered = filtered_path or (CACHE_DIR / "off_spain.jsonl")
    if not filtered.exists():
        dump = dump_path or download()
        filter_spain(dump, filtered)

    parsed: list[ParsedFood] = []
    rejections: list[Rejection] = []
    read = 0
    with filtered.open(encoding="utf-8") as f:
        for line in f:
            read += 1
            raw = json.loads(line)
            result = parse_food(raw)
            if isinstance(result, Rejection):
                rejections.append(result)
            else:
                parsed.append(result)

    stats = LoadStats(read=read, rejected=len(rejections))

    conn = get_connection()
    try:
        stats.upserted = upsert_foods(conn, parsed)
    finally:
        conn.close()

    rejected_path = log_rejections("off", rejections) if rejections else None
    return OffLoadResult(stats=stats, rejected_path=rejected_path)


def load_by_brand_dump(
    brands: Sequence[str] = DEFAULT_TARGET_BRANDS,
    country: str = "en:spain",
    dump_path: Path | None = None,
    filtered_path: Path | None = None,
) -> OffLoadResult:
    """Carga productos de marca filtrando el dump local con DuckDB en vez de
    la Search API (ver docstring de `filter_brands` — la API pública limita
    la paginación anónima a 1.000 resultados por consulta; el dump local no
    tiene ese límite). Reutiliza `parse_food()` sin cambios — mismas reglas
    de descarte que el resto de fuentes, nunca se relaja nada.

    Probado en la práctica el 2026-09-11 y descartado como fuente principal:
    el dump estático da una tasa de completitud de nutrientes muchísimo peor
    que la misma consulta contra la API en vivo para las mismas marcas
    (97,8% de descartes por `MISSING_KCAL` sobre 38.264 productos filtrados,
    frente a ~5% al pedir las mismas marcas vía `load_by_brand()`) — lectura
    más plausible: el dump es una foto periódica y estas marcas reciben
    ediciones comunitarias continuas que tardan en llegar al siguiente
    volcado. Se deja implementada y testeada (útil para una sincronización
    completa sin los límites de paginación de la API), pero `run.py` usa
    `load_by_brand()` como fuente principal de `--source off_brands`.
    """
    filtered = filtered_path or (CACHE_DIR / "off_brands.jsonl")
    if not filtered.exists():
        dump = dump_path or download()
        filter_brands(dump, filtered, brands, country)

    parsed: list[ParsedFood] = []
    rejections: list[Rejection] = []
    read = 0
    with filtered.open(encoding="utf-8") as f:
        for line in f:
            read += 1
            raw = json.loads(line)
            result = parse_food(raw)
            if isinstance(result, Rejection):
                rejections.append(result)
            else:
                parsed.append(result)

    stats = LoadStats(read=read, rejected=len(rejections))

    conn = get_connection()
    try:
        stats.upserted = upsert_foods(conn, parsed)
    finally:
        conn.close()

    rejected_path = log_rejections("off_brands", rejections) if rejections else None
    return OffLoadResult(stats=stats, rejected_path=rejected_path)


_ANONYMOUS_RESULT_CAP = 1000


def _api_get(client: httpx.Client, params: dict, retries: int = 8) -> dict:
    """GET contra la Search API con reintento exponencial (503 frecuente bajo carga)."""
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = client.get(SEARCH_API_URL, params=params, timeout=30.0)
            if resp.status_code == 503:
                raise httpx.HTTPStatusError("503", request=resp.request, response=resp)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            last_exc = exc
            time.sleep(min(2.0 * (attempt + 1), 20.0))
    raise RuntimeError(f"OFF Search API failed after {retries} retries: {last_exc}")


def fetch_brand_products(
    client: httpx.Client,
    brand: str,
    country: str = "spain",
    page_size: int = 100,
    fields: str = _API_FIELDS,
) -> Iterator[dict]:
    """Pagina la Search API v2 para una marca — para cuando una página viene corta.

    La API anónima solo sirve los primeros `_ANONYMOUS_RESULT_CAP` resultados: la página
    siguiente da 401/503 y reintentarla solo alarga la carga.
    """
    page = 1
    while page * page_size <= _ANONYMOUS_RESULT_CAP:
        data = _api_get(
            client,
            {
                "brands_tags": brand,
                "countries_tags_en": country,
                "page_size": page_size,
                "page": page,
                "fields": fields,
            },
        )
        products = data.get("products", [])
        if not products:
            return
        yield from products
        if len(products) < page_size:
            return
        page += 1
        time.sleep(1.5)  # cortesía con la API pública, sin límite fijado en sección 11.2


def load_by_brand(
    brands: Sequence[str] = DEFAULT_TARGET_BRANDS, country: str = "spain"
) -> OffLoadResult:
    """Carga productos de marca vía la Search API filtrando por marca en vez de
    solo por país (documento 2, sección 11).

    Investigado el 2026-09-11: filtrar el dump completo solo por
    `countries_tags` (`load()` arriba) da 358.342 productos etiquetados
    España pero el 94,7% no tiene ningún nutriente relleno — mayormente
    altas de solo código de barras. Consultando la misma Search API pública
    por `brands_tags` (marcas de supermercado con mucho tráfico de escaneo
    y edición comunitaria) la tasa de completitud es radicalmente distinta:
    solo `brands_tags=hacendado&countries_tags_en=spain` ya da 10.807
    resultados con nutrientes reales, muestreados y confirmados con
    `curl` antes de escribir este código. Reutiliza `parse_food()` sin
    cambios — incluidas todas las reglas de descarte de sección 11.2, nunca
    se relaja nada para forzar el número.

    Hace upsert marca a marca (no acumula todo en memoria hasta el final):
    la API pública devuelve 503 con cierta frecuencia bajo carga sostenida
    (confirmado en la práctica), así que si una marca falla tras agotar
    reintentos, el progreso de las marcas ya procesadas queda guardado en
    Postgres y se sigue con la siguiente en vez de perder toda la carga.
    """
    seen_barcodes: set[str] = set()
    total_read = 0
    total_upserted = 0
    total_rejected = 0
    all_rejections: list[Rejection] = []
    failed_brands: list[str] = []

    with httpx.Client(headers={"User-Agent": USER_AGENT}) as client:
        for brand in brands:
            brand_parsed: list[ParsedFood] = []
            brand_rejections: list[Rejection] = []
            brand_read = 0
            try:
                for raw in fetch_brand_products(client, brand, country):
                    code = str(raw.get("code") or "")
                    if code and code in seen_barcodes:
                        continue  # un producto puede matchear más de una marca-tag
                    if code:
                        seen_barcodes.add(code)
                    brand_read += 1
                    result = parse_food(raw)
                    if isinstance(result, Rejection):
                        brand_rejections.append(result)
                    else:
                        brand_parsed.append(result)
            except RuntimeError as exc:
                print(f"[off_brands] {brand}: FALLÓ tras agotar reintentos ({exc})")
                failed_brands.append(brand)

            total_read += brand_read
            total_rejected += len(brand_rejections)
            all_rejections.extend(brand_rejections)

            if brand_parsed:
                conn = get_connection()
                try:
                    upserted = upsert_foods(conn, brand_parsed)
                finally:
                    conn.close()
                total_upserted += upserted
                print(
                    f"[off_brands] {brand}: leídos={brand_read} "
                    f"cargados={upserted} descartados={len(brand_rejections)}"
                )
            time.sleep(2.0)  # cortesía entre marcas

    stats = LoadStats(read=total_read, upserted=total_upserted, rejected=total_rejected)
    if failed_brands:
        print(f"[off_brands] marcas fallidas (reintentar aparte): {failed_brands}")

    rejected_path = log_rejections("off_brands", all_rejections) if all_rejections else None
    return OffLoadResult(stats=stats, rejected_path=rejected_path)


_ALLERGEN_FIELDS = "code,allergens_tags,traces_tags"


def load_allergens_by_brand(
    brands: Sequence[str] = DEFAULT_TARGET_BRANDS, country: str = "spain"
) -> LoadStats:
    """Carga las etiquetas de alérgenos DECLARADAS por el fabricante (`allergens_tags`)
    y las trazas (`traces_tags`) de los productos de marca que ya están en `foods`.

    El ETL inicial (`load_by_brand`) solo pedía nutrientes, así que `food_allergens`
    se quedó vacía y el filtro de alérgenos no excluía nada. Se vuelve a paginar la
    misma Search API por marca pidiendo solo `code,allergens_tags,traces_tags`, y se
    enlaza por código de barras con los productos ya cargados. Marca a marca, como
    `load_by_brand`: si una falla tras agotar reintentos, lo ya cargado se conserva."""
    stats = LoadStats()
    failed: list[str] = []
    seen: set[str] = set()
    with httpx.Client(headers={"User-Agent": USER_AGENT}) as client:
        for brand in brands:
            by_code: dict[str, tuple[set[str], set[str]]] = {}
            try:
                for raw in fetch_brand_products(client, brand, country, fields=_ALLERGEN_FIELDS):
                    code = str(raw.get("code") or "")
                    if not code or code in seen:
                        continue
                    seen.add(code)
                    stats.read += 1
                    declared = off_tags_to_codes(raw.get("allergens_tags"))
                    traces = off_tags_to_codes(raw.get("traces_tags")) - declared
                    by_code[code] = (declared, traces)
            except RuntimeError as exc:
                print(f"[off_allergens] {brand}: FALLÓ tras agotar reintentos ({exc})")
                failed.append(brand)

            conn = get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, barcode_ean FROM foods "
                        "WHERE source = 'off' AND barcode_ean = ANY(%s)",
                        (list(by_code),),
                    )
                    id_by_code = {row[1]: row[0] for row in cur.fetchall()}
                rows = []
                for code, (declared, traces) in by_code.items():
                    food_id = id_by_code.get(code)
                    if food_id is None:
                        stats.rejected += 1  # en OFF pero no cargado en `foods`
                        continue
                    rows += [(food_id, c, "declared") for c in sorted(declared)]
                    rows += [(food_id, c, "trace") for c in sorted(traces)]
                stats.upserted += replace_allergens(
                    conn, id_by_code.values(), rows, origins=("declared", "trace")
                )
            finally:
                conn.close()
            print(f"[off_allergens] {brand}: productos={len(by_code)} filas={stats.upserted}")
            time.sleep(2.0)

    if failed:
        print(f"[off_allergens] marcas fallidas (reintentar aparte): {failed}")
    return stats


_IMAGE_FIELDS = (
    "code,image_front_url,image_ingredients_url,image_nutrition_url,image_packaging_url"
)
_IMAGE_TYPES = {
    "front": "image_front_url",
    "ingredients": "image_ingredients_url",
    "nutrition": "image_nutrition_url",
    "packaging": "image_packaging_url",
}
# Las imágenes de OFF son CC BY-SA: exigen atribución (sección 12).
IMAGE_LICENSE = "CC BY-SA"
IMAGE_ATTRIBUTION = "Open Food Facts"
_IMAGE_HOSTS = ("https://images.openfoodfacts.org/", "https://static.openfoodfacts.org/")


def image_rows_for_product(raw: dict) -> list[tuple[str, str]]:
    """(tipo, url) de las imágenes de un producto de la API que estén en el dominio de
    imágenes de OFF y por HTTPS — nunca se guarda una URL de otro origen."""
    out = []
    for image_type, field in _IMAGE_TYPES.items():
        url = raw.get(field)
        if isinstance(url, str) and url.startswith(_IMAGE_HOSTS):
            out.append((image_type, url))
    return out


def load_images_by_brand(
    brands: Sequence[str] = DEFAULT_TARGET_BRANDS, country: str = "spain"
) -> LoadStats:
    """Registra las URLs de imagen (`food_images.remote_url`) de los productos de marca ya
    cargados, enlazando por código de barras. No descarga ninguna imagen."""
    stats = LoadStats()
    failed: list[str] = []
    seen: set[str] = set()
    with httpx.Client(headers={"User-Agent": USER_AGENT}) as client:
        for brand in brands:
            by_code: dict[str, list[tuple[str, str]]] = {}
            try:
                for raw in fetch_brand_products(client, brand, country, fields=_IMAGE_FIELDS):
                    code = str(raw.get("code") or "")
                    if not code or code in seen:
                        continue
                    seen.add(code)
                    stats.read += 1
                    if images := image_rows_for_product(raw):
                        by_code[code] = images
            except RuntimeError as exc:
                print(f"[off_images] {brand}: FALLÓ tras agotar reintentos ({exc})")
                failed.append(brand)

            conn = get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, barcode_ean FROM foods "
                        "WHERE source = 'off' AND barcode_ean = ANY(%s)",
                        (list(by_code),),
                    )
                    id_by_code = {row[1]: row[0] for row in cur.fetchall()}
                rows = [
                    (id_by_code[code], image_type, url, "off", IMAGE_LICENSE, IMAGE_ATTRIBUTION)
                    for code, images in by_code.items()
                    if code in id_by_code
                    for image_type, url in images
                ]
                stats.upserted += upsert_images(conn, rows)
            finally:
                conn.close()
            print(f"[off_images] {brand}: productos={len(by_code)} filas={stats.upserted}")
            time.sleep(2.0)

    if failed:
        print(f"[off_images] marcas fallidas (reintentar aparte): {failed}")
    return stats
