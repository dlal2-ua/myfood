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
```

## Fuentes implementadas

| Fuente | `quality_rank` | Alcance | Estado |
|---|---|---|---|
| USDA Foundation | 1 | 95 alimentos genéricos cargados (de 395 leídos — el resto sin `kcal` reportado, p. ej. sal) | ✅ |
| USDA SR Legacy | 2 | 7.783 alimentos genéricos | ✅ |
| CIQUAL (ANSES) | 3 | 2.293 alimentos genéricos (de 3.186 leídos) | ✅ |
| Open Food Facts (España) | 5 | **31** productos de marca (de 358.342 filtrados por `en:spain`) | ⚠️ ver nota abajo |
| BEDCA | 4 | ~500 alimentos españoles de referencia | ⏳ pendiente (servicio SOAP) |

Total genérico cargado tras USDA+CIQUAL: **10.171** — supera el criterio de
aceptación de la Fase 1 (≥8.000 alimentos genéricos).

### ⚠️ OFF-España no alcanza el criterio de ≥10.000 productos de marca

Verificado en profundidad el 2026-09-11, no es un bug del pipeline (descartado
con varias comprobaciones independientes, incluida la lectura del dump crudo
sin pasar por DuckDB para descartar corrupción en el filtrado): del dump
completo de OFF (~13 GB, ~4M productos), **358.342 traen la etiqueta
`en:spain`**, pero de ellos **el 94,7% no tiene ningún nutriente cargado en
absoluto** (`nutriments` vacío en el propio dump estático, no solo tras
filtrar) — una entrada de solo código de barras + foto, sin datos
nutricionales nunca rellenados por ningún contribuidor. Confirmado uniforme
en varios puntos del fichero (inicio, ~100.000 registros después), no es un
sesgo de muestreo. Tras aplicar las reglas de descarte de la sección 11.2
(sin `kcal_100g`, o `kcal_100g > 900`, o macros > 100 g — nunca estimadas),
solo **31 productos** pasan la validación.

Esto es una característica real del propio dataset público, no un fallo de
esta implementación — se deja documentado en vez de forzar el número
relajando las reglas de descarte (lo que violaría R9). Pendiente de decisión
del usuario: aceptar un catálogo de marca inicial pequeño (crece con
actualizaciones incrementales de OFF y con las altas manuales de usuarios
al escanear, sección 11.2 y Fase 2), o explorar una fuente complementaria
para productos españoles de marca.

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
