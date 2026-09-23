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
| BEDCA (AESAN) | 4 | 429 alimentos de referencia cargados (de 431 leídos — 431 es el total real con `f_origen == "BEDCA"` exacto, filtrado de >2.300 registros de toda la red BEDCA que incluye aportaciones de universidades colaboradoras bajo otros orígenes) | ✅ |
| Open Food Facts (España) | 5 | **11.190** productos de marca (ver nota abajo) | ✅ |

Total genérico cargado tras USDA+CIQUAL+BEDCA: **10.600** — supera el
criterio de aceptación de la Fase 1 (≥8.000 alimentos genéricos). Total de
marca (OFF): **11.190** — supera el criterio de ≥10.000 productos de marca.

## Recetario compartido (TheMealDB)

Pipeline aparte del de alimentos: trae PLATOS, no nutrientes. De la API se
toman ingredientes, cantidades, pasos y foto; las calorías las calcula
MyFood sumando los `food_nutrients` de los ingredientes que empareja con su
propio catálogo (R9). Nada de lo que devuelve la API se usa como número.

```bash
uv run python -m etl.import_themealdb --dry-run    # ensayo, sin escribir ni traducir
uv run python -m etl.import_themealdb --skip-steps # todo menos los pasos (lo caro)
uv run python -m etl.import_themealdb --repair     # rehace lo ya importado, casi gratis
uv run python -m etl.import_themealdb              # completo
```

| Fuente | Alcance | Estado |
|---|---|---|
| TheMealDB | 790 recetas (el catálogo entero, contado letra a letra) | ✅ |

La traducción al español se hace con Claude y es la parte cara: la primera
importación costó **1.011.112 tokens de salida**. Por eso todo lo traducido
se guarda en `data/cache/themealdb.json` según sale, y las recetas se
escriben en la base de datos de ocho en ocho, no al final: una importación
cortada no vuelve a pagar lo que ya estaba hecho.

`--repair` aprovecha eso al máximo — lee de la base de datos las
traducciones de la importación anterior, las mete en la caché y solo pide lo
que falte. Es lo que hay que usar para arreglar emparejados o taxonomías sin
volver a gastar un millón de tokens.

Las cocinas y las categorías NO se traducen con IA: son vocabulario cerrado
y están en tablas (`AREA_ES`, `CATEGORY_ES` en `sources/themealdb.py`). Lo
que no esté en la tabla se deja en inglés y se avisa por pantalla, que se ve;
una traducción inventada, no.

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

### Nota sobre BEDCA: no es SOAP/WSDL, es HTTP+XML propio

La WSDL histórica (`bdpub/procedure_call.php?wsdl`) ya no existe (404).
Verificado en vivo el 2026-09-11: el servicio real es
`https://www.bedca.net/bdpub/procquery.php`, que recibe una petición XML
(`<foodquery>`) por HTTP POST (`Content-Type: text/xml`) y devuelve una
respuesta XML (`<foodresponse>`) — no hay envoltorio SOAP real, así que no
hizo falta añadir `zeep` (cliente SOAP) como dependencia; `httpx` (ya en
`pyproject.toml`) más `xml.etree.ElementTree` (stdlib) bastan. Los tres tipos
de consulta (grupos, alimentos de un grupo, detalle de un alimento) se
confirmaron contra el servicio real y contra un cliente PHP de terceros ya
existente (`github.com/statickidz/bedca-api`, MIT).

La red BEDCA agrega datos de más de 2.300 alimentos entre el propio equipo
BEDCA y universidades colaboradoras (UCM, UGR, UCO, CESNID y otras, cada una
con su propio `f_origen`). Se cargan solo los 431 alimentos con
`f_origen == "BEDCA"` exacto — el conjunto de referencia oficial que
describe el README original del proyecto (~500) — filtrando en cliente,
porque el propio filtro de condición del servicio hace coincidencia por
subcadena y devolvía también `BEDCA2` (91+59=150 resultados pidiendo solo
"BEDCA" en el grupo de lácteos, verificado). BEDCA ya normaliza todo "por
100 g de porción comestible" (no hace falta convertir por ración), pero solo
reporta la energía en kJ — se convierte a kcal dividiendo por 4.184.

## Reglas (sección 11.2)

- Conversión a 100 g obligatoria — USDA y CIQUAL ya vienen normalizados así,
  no hace falta convertir por porción.
- Descarte (a `etl/rejected/<fuente>.jsonl`, no versionado): sin `kcal_100g`,
  `kcal_100g > 900`, o `proteína+grasa+carbohidratos > 100 g`. Nunca se
  estima un valor que falte.
- Idempotencia: upsert por `(source, source_id)` — reejecutar no duplica
  (índice único `foods_source_source_id_idx`, migración 0003).
- Mapeo de nutrientes explícito en `transform/nutrient_map.py` — por ID
  (USDA), cabecera exacta (CIQUAL) o código `eur_name` de componente
  (BEDCA), nunca por coincidencia de nombre.

## Tests

```bash
uv run pytest        # etl/tests/ — muestras reales pequeñas en etl/fixtures/
uv run ruff check etl
```

Los tests de transformación (`parse_food`) son puros — no tocan la base de
datos, solo la lógica de mapeo/descarte, con fixtures extraídas de los
dumps reales.

## Índice de Meilisearch y filtros del catálogo

`python -m etl.index` reindexa el catálogo entero (idempotente, ~10 s para 22.000 alimentos) y
deja configurados los atributos filtrables. Además de los campos del buscador, cada documento
lleva lo que necesita la pantalla «Alimentos» para filtrar:

- `supermarket`: cadena a la que pertenece la marca de OFF (Mercadona, Lidl…), con
  `myfood.domain.food_taxonomy.supermarket_for_brand`.
- `food_group`: tipo de alimento (`myfood.domain.food_groups`, el mismo que usa el motor de dietas).
- `nutrition_tags`: etiquetas por 100 g (alto en proteína, bajo en grasa…) con los umbrales de las
  declaraciones nutricionales del Reglamento (CE) 1924/2006.

La taxonomía vive en la API (`apps/api/src/myfood/domain/food_taxonomy.py`, Python puro) y el ETL
la importa por ruta: una sola definición para el índice y para los filtros de la web. **Hay que
reindexar tras desplegar cualquier cambio de esa taxonomía o del ETL**; si el índice es antiguo,
los filtros nuevos no encuentran nada.
