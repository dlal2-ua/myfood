# etl

Ingesta de datos nutricionales (documento 2, sección 11). Proyecto Python
independiente de `apps/api` (`pyproject.toml` en la raíz del repo), con su
propio entorno gestionado por `uv`.

## Uso

```bash
cd myfood  # raíz del repo
uv sync
export POSTGRES_HOST=localhost POSTGRES_PASSWORD=...  # credenciales del rol superusuario
uv run python -m etl.run --source usda_foundation
uv run python -m etl.run --source usda_sr
uv run python -m etl.run --source ciqual
uv run python -m etl.run --source bedca
uv run python -m etl.run --source off          # dump completo filtrado por país (referencia histórica)
uv run python -m etl.run --source off_brands   # productos de marca, ver nota abajo
```

## Fuentes implementadas

| Fuente | `quality_rank` | Alcance | Estado |
|---|---|---|---|
| USDA Foundation | 1 | 95 alimentos genéricos cargados (de 395 leídos — el resto sin `kcal` reportado, p. ej. sal) | ✅ |
| USDA SR Legacy | 2 | 7.783 alimentos genéricos | ✅ |
| CIQUAL (ANSES) | 3 | 2.293 alimentos genéricos (de 3.186 leídos) | ✅ |
| BEDCA (AESAN) | 4 | 429 alimentos de referencia (de 431 leídos, ver `etl/sources/bedca.py`) | ✅ |
| Open Food Facts (España) | 5 | **11.190** productos de marca (ver nota abajo) | ✅ |

Total genérico cargado tras USDA+CIQUAL+BEDCA: **10.600** — supera el
criterio de aceptación de la Fase 1 (≥8.000 alimentos genéricos). Total de
marca (OFF): **11.190** — supera el criterio de ≥10.000 productos de marca.

### Open Food Facts España: de 31 a 11.190 productos de marca

Investigación en dos fases, documentada aquí porque el camino hasta llegar
al número correcto no es obvio y vale la pena dejarlo por si hace falta
repetirlo con otra fuente en el futuro.

**Fase 1 — por qué filtrar el dump solo por país no sirve.** El dump
completo de OFF (~13 GB, ~4M productos) trae 358.342 productos con la
etiqueta `en:spain`, pero el 94,7% no tiene ningún nutriente cargado en
absoluto (`nutriments` vacío en el propio dump estático, no solo tras
filtrar) — altas de solo código de barras + foto, nunca rellenadas por
ningún contribuidor. Verificado que no es un bug de lectura leyendo la
línea cruda del dump directamente con `gzip`/`json`, sin DuckDB de por
medio, y confirmado uniforme en varios puntos del fichero (no es sesgo de
muestreo). Tras las reglas de descarte de la sección 11.2, solo 31
productos pasaban.

**Fase 2 — la Search API pública por marca sí tiene los datos.**
Consultando la misma API en vivo de OFF filtrando por `brands_tags` (marcas
de supermercado con mucho tráfico de escaneo/edición comunitaria) en vez de
solo por país, la completitud es radicalmente distinta:
`brands_tags=hacendado&countries_tags_en=spain` da 10.807 resultados con
nutrientes reales — confirmado con muestras reales antes de escribir
código. Se probó primero replicar esto filtrando el dump local por
`brands_tags` con DuckDB (sin los límites de la API), pero el dump dio una
tasa de descarte del 97,8% para las mismas marcas — muy por encima de lo
que da la API en vivo para las mismas marcas (~5-8%). La lectura más
plausible es que el dump es una foto periódica y estas marcas reciben
ediciones comunitarias continuas que tardan en llegar al siguiente volcado.
Esa ruta (`etl/sources/off.py::load_by_brand_dump`) se deja implementada y
testeada por si hace falta una sincronización completa sin los límites de
paginación de la API, pero no es la fuente principal.

La API pública limita la paginación anónima a los primeros 1.000
resultados por consulta (confirmado en la práctica: 401/503 exactamente en
la página 11 con `page_size=100`, y solo en marcas cuyo `count` supera
1.000) — en vez de registrar una cuenta de OFF, se amplió la lista de
marcas consultadas (`DEFAULT_TARGET_BRANDS` en `etl/sources/off.py`, 20
cadenas de supermercado españolas) hasta superar el criterio con margen:
cada consulta capada a 1.000 sigue dando una muestra bien poblada de esa
marca, y las cadenas más pequeñas (Alcampo, Condis, Ahorramas, Gadis,
Masymas, Froiz, Hipercor, Caprabo) no llegan a ese límite, así que su
recuento es completo. Resultado real cargado: **11.190** productos de
marca únicos (`etl/sources/off.py::load_by_brand`, `--source off_brands`).

## Reglas (sección 11.2)

- Conversión a 100 g obligatoria — USDA y CIQUAL ya vienen normalizados así,
  no hace falta convertir por porción.
- Descarte (a `etl/rejected/<fuente>.jsonl`, no versionado): sin `kcal_100g`,
  `kcal_100g > 900`, o `proteína+grasa+carbohidratos > 100 g`. Nunca se
  estima un valor que falte.
- Idempotencia: upsert por `(source, source_id)` — reejecutar no duplica
  (índice único `foods_source_source_id_idx`, migración 0003).
- Mapeo de nutrientes explícito en `transform/nutrient_map.py` — por ID
  (USDA) o cabecera exacta (CIQUAL), nunca por coincidencia de nombre.

## Tests

```bash
uv run pytest        # etl/tests/ — muestras reales pequeñas en etl/fixtures/
uv run ruff check etl
```

Los tests de transformación (`parse_food`) son puros — no tocan la base de
datos, solo la lógica de mapeo/descarte, con fixtures extraídas de los
dumps reales.
