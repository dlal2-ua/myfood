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
| USDA Foundation | 1 | ~95 alimentos genéricos cargados (de 395 leídos — el resto sin `kcal` reportado, p. ej. sal) | ✅ |
| USDA SR Legacy | 2 | ~7.783 alimentos genéricos | ✅ |
| CIQUAL (ANSES) | 3 | ~2.293 alimentos genéricos (de 3.186 leídos) | ✅ |
| BEDCA | 4 | ~500 alimentos españoles de referencia | ⏳ pendiente (servicio SOAP) |
| Open Food Facts (España) | 5 | Productos de marca | ⏳ pendiente (dump JSONL + DuckDB) |

Total generic cargado tras USDA+CIQUAL: **10.171** — supera el criterio de
aceptación de la Fase 1 (≥8.000) sin necesitar BEDCA todavía.

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
