"""Trae el recetario de TheMealDB al catálogo compartido de MyFood.

De la API se toma el PLATO — ingredientes, cantidades, pasos y foto — nunca sus números: la
nutrición la calcula MyFood sumando `food_nutrients` de los ingredientes que empareja con su
propio catálogo (R9), igual que con una receta escrita a mano.

El orden importa y es lo que abarata el proceso:

1. Se traen los platos (sin coste: es una API pública).
2. Se traducen los nombres de ingredientes DEDUPLICADOS. Entre 790 recetas hay unos 575
   ingredientes distintos, así que traducir la lista única en vez de receta por receta ahorra
   la mayor parte del trabajo.
3. Se traducen los nombres de los platos.
4. Se empareja cada ingrediente con el catálogo y se resuelven sus gramos con las mismas
   tablas que usa el resto de la app.
5. Se traducen los pasos de cocina, que es la parte cara: son el 80 % del texto.

    python -m etl.import_themealdb --dry-run          # sin escribir ni traducir
    python -m etl.import_themealdb --skip-steps       # todo menos los pasos (barato)
    python -m etl.import_themealdb                    # completo

Se informa del gasto real en tokens al terminar.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import unicodedata

import httpx

from etl.db import get_connection
from etl.sources import themealdb
from etl.sources.measures_en import to_spanish_quantity

BATCH_NAMES = 60
BATCH_STEPS = 8
TIMEOUT_SECONDS = 180.0
MIN_GRAMS, MAX_GRAMS = 1.0, 3000.0
DEFAULT_SERVINGS = 4

INGREDIENT_PROMPT = """Traduces al español de España nombres de ingredientes de cocina.
Devuelve SOLO un array JSON de strings, mismo orden y mismo número de elementos que la entrada.
Usa el término corriente en España: «nata» y no «crema», «patata» y no «papa», «gambas» y no
«camarones», «zumo» y no «jugo». Sin explicaciones ni markdown."""

TITLE_PROMPT = """Traduces al español de España nombres de platos de cocina internacional.
Mantén el nombre propio del plato cuando es conocido así (Ratatouille, Pad Thai, Chow Mein) y
traduce el resto. Devuelve SOLO un array JSON de strings, mismo orden y mismo número de
elementos que la entrada. Sin explicaciones ni markdown."""

STEPS_PROMPT = """Traduces al español de España los pasos de elaboración de una receta.
Mantén el texto completo y el orden de los pasos: no resumas, no añadas nada y no quites
ningún detalle de tiempos ni temperaturas. Convierte las medidas inglesas a su nombre español
(cup→taza, tablespoon→cucharada) pero NO cambies las cantidades. Los grados Fahrenheit se
dejan con su equivalente en centígrados entre paréntesis.
Devuelve SOLO un array JSON de strings, mismo orden y mismo número de elementos que la
entrada. Sin explicaciones ni markdown."""


class Spend:
    """Lo que ha costado, en tokens de verdad, no estimados."""

    def __init__(self) -> None:
        self.input = 0
        self.output = 0
        self.calls = 0

    def add(self, result) -> None:
        self.calls += 1
        self.input += result.input_tokens or 0
        self.output += result.output_tokens or 0

    def __str__(self) -> str:
        return (
            f"{self.calls} llamadas · {self.input:,} tokens de entrada · "
            f"{self.output:,} de salida"
        )


def _api():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api", "src"))
    from myfood.ai.agent import AiAgentError, run_agent
    from myfood.ai.client import get_decrypted_token
    from myfood.db.session import AdminSessionLocal
    from myfood.domain.quantity_text import resolve_grams

    return AiAgentError, run_agent, get_decrypted_token, AdminSessionLocal, resolve_grams


def parse_list(text: str, expected: int) -> list[str] | None:
    """Igual que en `translate_names`: un lote que no cuadra se descarta entero, porque
    emparejar mal renombraría un plato con el nombre de otro."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end == -1:
        return None
    try:
        parsed = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list) or len(parsed) != expected:
        return None
    if not all(isinstance(item, str) and item.strip() for item in parsed):
        return None
    return [item.strip() for item in parsed]


async def translate(items: list[str], system: str, batch: int, spend: Spend, token: str) -> dict:
    """`{original: traducción}`. Lo que falle se queda sin traducir, no se inventa."""
    AiAgentError, run_agent, *_ = _api()
    out: dict[str, str] = {}
    for start in range(0, len(items), batch):
        chunk = items[start : start + batch]
        try:
            result = await run_agent(
                token=token,
                prompt=json.dumps(chunk, ensure_ascii=False),
                system_prompt=system,
                timeout_seconds=TIMEOUT_SECONDS,
            )
        except AiAgentError as exc:
            print(f"  lote {start // batch + 1}: falló ({exc})", flush=True)
            continue
        spend.add(result)
        translated = parse_list(result.text, len(chunk))
        if translated is None:
            print(f"  lote {start // batch + 1}: respuesta descartada", flush=True)
            continue
        out.update(dict(zip(chunk, translated, strict=True)))
        print(f"  {min(start + batch, len(items))}/{len(items)} · {spend}", flush=True)
    return out


def _normalize(text: str) -> str:
    stripped = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in stripped if unicodedata.category(c) != "Mn")


def match_foods(names: list[str]) -> dict[str, tuple[str, str, str | None]]:
    """Empareja cada ingrediente con un alimento del catálogo: `{nombre: (id, nombre, categoría)}`.

    Se buscan solo alimentos GENÉRICOS (BEDCA, USDA, CIQUAL) y no productos de marca: la receta
    dice «cebolla», no «cebolla de Mercadona», y un genérico es lo que corresponde. Se ordena
    por `quality_rank` y por lo corto que sea el nombre — «Cebolla, cruda» antes que «Cebolla
    deshidratada en polvo, enriquecida»."""
    out: dict[str, tuple[str, str, str | None]] = {}
    with get_connection() as conn, conn.cursor() as cur:
        for name in names:
            cur.execute(
                """
                SELECT f.id::text, f.name_es, f.category
                FROM foods f JOIN food_nutrients n ON n.food_id = f.id
                WHERE f.source IN ('bedca', 'usda_sr', 'usda_foundation', 'ciqual')
                  AND f.name_es ILIKE %s
                ORDER BY f.quality_rank, length(f.name_es)
                LIMIT 1
                """,
                (f"%{name}%",),
            )
            row = cur.fetchone()
            if row is None and " " in name:
                # «pechuga de pollo cruda» puede no estar tal cual: se prueba con la cabeza.
                head = name.split()[0]
                cur.execute(
                    """
                    SELECT f.id::text, f.name_es, f.category
                    FROM foods f JOIN food_nutrients n ON n.food_id = f.id
                    WHERE f.source IN ('bedca', 'usda_sr', 'usda_foundation', 'ciqual')
                      AND f.name_es ILIKE %s
                    ORDER BY f.quality_rank, length(f.name_es)
                    LIMIT 1
                    """,
                    (f"%{head}%",),
                )
                row = cur.fetchone()
            if row is not None:
                out[name] = (row[0], row[1], row[2])
    return out


def save_recipes(rows: list[dict]) -> tuple[int, int]:
    """Guarda recetas del catálogo (`user_id IS NULL`). Devuelve `(recetas, ingredientes)`.

    Reimportar no duplica: la clave natural es (fuente, id en la fuente), y los ingredientes
    se reescriben enteros — es más simple y más seguro que intentar casarlos uno a uno."""
    recipes = ingredients = 0
    with get_connection() as conn, conn.cursor() as cur:
        for row in rows:
            cur.execute(
                """
                INSERT INTO recipes
                  (id, user_id, name, servings, instructions, source, source_id,
                   image_url, cuisine, category, attribution)
                VALUES (gen_random_uuid(), NULL, %s, %s, %s, 'themealdb', %s, %s, %s, %s, %s)
                ON CONFLICT (source, source_id) WHERE source_id IS NOT NULL
                DO UPDATE SET name = EXCLUDED.name, instructions = EXCLUDED.instructions,
                              image_url = EXCLUDED.image_url, cuisine = EXCLUDED.cuisine,
                              category = EXCLUDED.category
                RETURNING id
                """,
                (
                    row["name"],
                    row["servings"],
                    row["instructions"],
                    row["source_id"],
                    row["image_url"],
                    row["cuisine"],
                    row["category"],
                    themealdb.ATTRIBUTION,
                ),
            )
            recipe_id = cur.fetchone()[0]
            recipes += 1
            cur.execute("DELETE FROM recipe_ingredients WHERE recipe_id = %s", (recipe_id,))
            for food_id, grams in row["ingredients"]:
                cur.execute(
                    "INSERT INTO recipe_ingredients (id, recipe_id, food_id, grams) "
                    "VALUES (gen_random_uuid(), %s, %s, %s)",
                    (recipe_id, food_id, grams),
                )
                ingredients += 1
        conn.commit()
    return recipes, ingredients


async def run(dry_run: bool, skip_steps: bool, limit: int | None) -> int:
    _AiAgentError, _run_agent, get_decrypted_token, AdminSessionLocal, resolve_grams = _api()

    print("[recetas] trayendo el catálogo de TheMealDB…", flush=True)
    with httpx.Client(timeout=themealdb.REQUEST_TIMEOUT) as client:
        raw = themealdb.fetch_all(client)
    if limit:
        raw = raw[:limit]
    print(f"[recetas] {len(raw)} platos", flush=True)

    async with AdminSessionLocal() as session:
        token = await get_decrypted_token(session)
    if token is None:
        print("No hay credencial de iafood configurada.", file=sys.stderr)
        return 1

    spend = Spend()

    unique_ingredients = sorted({i.name for r in raw for i in r.ingredients})
    print(f"\n[recetas] traduciendo {len(unique_ingredients)} ingredientes distintos…", flush=True)
    ingredient_es = await translate(
        unique_ingredients, INGREDIENT_PROMPT, BATCH_NAMES, spend, token
    )

    print(f"\n[recetas] traduciendo {len(raw)} nombres de plato…", flush=True)
    title_es = await translate([r.name for r in raw], TITLE_PROMPT, BATCH_NAMES, spend, token)

    steps_es: dict[str, str] = {}
    if not skip_steps:
        print(f"\n[recetas] traduciendo los pasos de {len(raw)} recetas…", flush=True)
        steps_es = await translate(
            [r.instructions for r in raw], STEPS_PROMPT, BATCH_STEPS, spend, token
        )

    print("\n[recetas] emparejando ingredientes con el catálogo…", flush=True)
    matches = match_foods(sorted(set(ingredient_es.values())))
    print(f"[recetas] {len(matches)}/{len(ingredient_es)} ingredientes encontrados", flush=True)

    rows = []
    sin_emparejar: set[str] = set()
    for recipe in raw:
        items = []
        for ingredient in recipe.ingredients:
            spanish = ingredient_es.get(ingredient.name, ingredient.name)
            match = matches.get(spanish)
            if match is None:
                sin_emparejar.add(spanish)
                continue
            food_id, food_name, category = match
            grams = resolve_grams(
                to_spanish_quantity(ingredient.measure),
                None,
                food_name=food_name,
                category=category,
            )
            items.append((food_id, max(MIN_GRAMS, min(float(grams), MAX_GRAMS))))
        if not items:
            continue  # sin un solo ingrediente emparejado no se puede calcular nada
        rows.append(
            {
                "name": title_es.get(recipe.name, recipe.name),
                "servings": DEFAULT_SERVINGS,
                "instructions": steps_es.get(recipe.instructions, recipe.instructions),
                "source_id": recipe.source_id,
                "image_url": recipe.image_url,
                "cuisine": recipe.cuisine,
                "category": recipe.category,
                "ingredients": items,
            }
        )

    print(f"\n[recetas] listas para guardar: {len(rows)} de {len(raw)}")
    if sin_emparejar:
        muestra = ", ".join(sorted(sin_emparejar)[:8])
        print(f"[recetas] {len(sin_emparejar)} ingredientes sin equivalente, p. ej.: {muestra}")

    if dry_run:
        for row in rows[:3]:
            print(f"\n  {row['name']} ({row['cuisine']}) · {len(row['ingredients'])} ingredientes")
            print(f"    {row['instructions'][:160]}…")
    else:
        recipes, ingredients = save_recipes(rows)
        print(f"[recetas] guardadas {recipes} recetas con {ingredients} ingredientes")

    print(f"\n[recetas] GASTO: {spend}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="no escribe en la base de datos")
    parser.add_argument(
        "--skip-steps", action="store_true", help="no traduce los pasos (lo más caro)"
    )
    parser.add_argument("--limit", type=int, default=None, help="solo las primeras N recetas")
    args = parser.parse_args()
    return asyncio.run(run(args.dry_run, args.skip_steps, args.limit))


if __name__ == "__main__":
    raise SystemExit(main())
