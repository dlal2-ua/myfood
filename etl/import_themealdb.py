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
    python -m etl.import_themealdb --repair           # arregla lo ya importado, casi gratis
    python -m etl.import_themealdb                    # completo

Lo traducido se guarda en disco según sale y las recetas se guardan por lotes, no al final.
La primera importación tardó cuarenta minutos y escribió en el último segundo: si se hubiera
cortado a la mitad, se habría tirado media hora de tokens ya pagados. Con la caché, repetir
una importación interrumpida no cuesta nada por lo que ya estaba hecho.

Se informa del gasto real en tokens al terminar.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

import httpx

from etl.db import get_connection
from etl.sources import themealdb
from etl.sources.measures_en import to_spanish_quantity
from etl.transform import food_match

BATCH_NAMES = 60
BATCH_STEPS = 8
# Cada cuántas recetas se escribe en la base de datos. Coincide con el lote de pasos porque
# es el trabajo caro: en cuanto un lote está traducido, se guarda y ya no se puede perder.
SAVE_EVERY = BATCH_STEPS
CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cache", "themealdb.json")
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


class Cache:
    """Lo ya traducido, en disco, para que una importación cortada no vuelva a pagarlo.

    Se escribe después de CADA lote, no al final: el fichero completo se vuelca a un temporal
    y se renombra encima, que es atómico en el mismo sistema de ficheros, así que un corte a
    mitad de escritura deja la versión anterior entera en vez de un JSON roto."""

    SECCIONES = ("ingredients", "titles", "steps")

    def __init__(self, path: str) -> None:
        self.path = path
        self.data: dict[str, dict[str, str]] = {s: {} for s in self.SECCIONES}
        try:
            with open(path, encoding="utf-8") as handle:
                stored = json.load(handle)
        except (FileNotFoundError, json.JSONDecodeError):
            return
        for section in self.SECCIONES:
            values = stored.get(section)
            if isinstance(values, dict):
                self.data[section] = {k: v for k, v in values.items() if isinstance(v, str)}

    def __len__(self) -> int:
        return sum(len(v) for v in self.data.values())

    def get(self, section: str) -> dict[str, str]:
        return self.data[section]

    def update(self, section: str, values: dict[str, str]) -> None:
        self.data[section].update(values)
        self.save()

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        temporary = f"{self.path}.tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(self.data, handle, ensure_ascii=False)
        os.replace(temporary, self.path)


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


async def translate(
    items: list[str],
    system: str,
    batch: int,
    spend: Spend,
    token: str,
    cache: Cache,
    section: str,
) -> dict:
    """`{original: traducción}`. Lo que falle se queda sin traducir, no se inventa.

    Lo que ya esté en la caché no se vuelve a pedir, y cada lote nuevo se guarda nada más
    llegar: así el gasto se conserva aunque la importación se corte después."""
    known = cache.get(section)
    out: dict[str, str] = {item: known[item] for item in items if item in known}
    pending = [item for item in items if item not in known]
    if out:
        print(f"  {len(out)} ya traducidos de antes", flush=True)
    for start in range(0, len(pending), batch):
        chunk = pending[start : start + batch]
        fresh = await translate_chunk(chunk, system, spend, token)
        if fresh:
            out.update(fresh)
            cache.update(section, fresh)
        print(f"  {min(start + batch, len(pending))}/{len(pending)} · {spend}", flush=True)
    return out


async def translate_chunk(chunk: list[str], system: str, spend: Spend, token: str) -> dict:
    """Un lote, partiéndolo en dos si la respuesta no cuadra.

    Un lote descartado se llevaba por delante las 60 traducciones que iba dentro, y así se
    quedaron sin traducir platos como «Egg Foo Young»: no falló el suyo, falló el vecino.
    Partir y reintentar aísla al culpable y salva al resto, y al llegar a uno solo ya no hay
    a quién culpar, así que ese se queda en inglés y se sigue."""
    AiAgentError, run_agent, *_ = _api()
    try:
        result = await run_agent(
            token=token,
            prompt=json.dumps(chunk, ensure_ascii=False),
            system_prompt=system,
            timeout_seconds=TIMEOUT_SECONDS,
        )
    except AiAgentError as exc:
        print(f"    lote de {len(chunk)}: falló ({exc})", flush=True)
        return {}
    spend.add(result)
    translated = parse_list(result.text, len(chunk))
    if translated is not None:
        return dict(zip(chunk, translated, strict=True))
    if len(chunk) == 1:
        print(f"    sin traducir: «{chunk[0][:60]}»", flush=True)
        return {}
    middle = len(chunk) // 2
    print(f"    lote de {len(chunk)} descartado, se parte en dos", flush=True)
    first = await translate_chunk(chunk[:middle], system, spend, token)
    second = await translate_chunk(chunk[middle:], system, spend, token)
    return {**first, **second}


def load_index() -> food_match.Index:
    """Trae los alimentos genéricos a memoria para emparejarlos con los ingredientes.

    Se buscan solo alimentos GENÉRICOS (BEDCA, USDA, CIQUAL) y no productos de marca: la
    receta dice «cebolla», no «cebolla de Mercadona», y un genérico es lo que corresponde. El
    orden es el de calidad de la fuente, y `food_match` lo usa de desempate."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT f.id::text, f.name_es, f.category
            FROM foods f JOIN food_nutrients n ON n.food_id = f.id
            WHERE f.source IN ('bedca', 'usda_sr', 'usda_foundation', 'ciqual')
            ORDER BY f.quality_rank, length(f.name_es)
            """
        )
        return food_match.build_index(cur.fetchall())


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


def seed_cache_from_db(cache: Cache, raw: list) -> int:
    """Mete en la caché lo que ya se tradujo en la importación anterior.

    Los pasos de las 790 recetas están traducidos y guardados en `recipes.instructions`, pero
    esa traducción costó un millón de tokens y la caché no existía todavía. Leyéndolos de la
    base de datos, arreglar lo demás no vuelve a pagarlos.

    Un título que en la base de datos siga siendo IGUAL que el inglés no se mete: ese es
    justo el que se quedó sin traducir y el que hay que volver a pedir."""
    por_id = {r.source_id: r for r in raw}
    titles: dict[str, str] = {}
    steps: dict[str, str] = {}
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT source_id, name, instructions FROM recipes "
            "WHERE source = 'themealdb' AND source_id = ANY(%s)",
            (list(por_id),),
        )
        for source_id, name, instructions in cur.fetchall():
            recipe = por_id[source_id]
            if name and name != recipe.name:
                titles[recipe.name] = name
            if instructions and instructions != recipe.instructions:
                steps[recipe.instructions] = instructions
    cache.update("titles", titles)
    cache.update("steps", steps)
    return len(titles) + len(steps)


def build_row(recipe, title_es: dict, steps_es: dict, ingredient_es: dict, index, resolve_grams):
    """La receta lista para guardar, o `None` si no se emparejó ni un ingrediente.

    Devuelve también los nombres que no encontraron nada, para poder contarlos al final."""
    items = []
    sin_emparejar: set[str] = set()
    for ingredient in recipe.ingredients:
        spanish = ingredient_es.get(ingredient.name, ingredient.name)
        food = food_match.match(spanish, index)
        if food is None:
            sin_emparejar.add(spanish)
            continue
        grams = resolve_grams(
            to_spanish_quantity(ingredient.measure),
            None,
            food_name=food.name,
            category=food.category,
        )
        items.append((food.id, max(MIN_GRAMS, min(float(grams), MAX_GRAMS))))
    if not items:
        return None, sin_emparejar
    return {
        "name": title_es.get(recipe.name, recipe.name),
        "servings": DEFAULT_SERVINGS,
        "instructions": steps_es.get(recipe.instructions, recipe.instructions),
        "source_id": recipe.source_id,
        "image_url": recipe.image_url,
        "cuisine": recipe.cuisine,
        "category": recipe.category,
        "ingredients": items,
    }, sin_emparejar


async def run(dry_run: bool, skip_steps: bool, limit: int | None, repair: bool) -> int:
    _AiAgentError, _run_agent, get_decrypted_token, AdminSessionLocal, resolve_grams = _api()

    print("[recetas] trayendo el catálogo de TheMealDB…", flush=True)
    with httpx.Client(timeout=themealdb.REQUEST_TIMEOUT) as client:
        raw = themealdb.fetch_all(client)
    if limit:
        raw = raw[:limit]
    print(f"[recetas] {len(raw)} platos", flush=True)
    if themealdb.SIN_TRADUCIR:
        pendientes = ", ".join(sorted(themealdb.SIN_TRADUCIR))
        print(f"[recetas] AVISO: cocinas o categorías sin traducir: {pendientes}", flush=True)

    async with AdminSessionLocal() as session:
        token = await get_decrypted_token(session)
    if token is None:
        print("No hay credencial de iafood configurada.", file=sys.stderr)
        return 1

    cache = Cache(CACHE_PATH)
    if repair:
        recuperados = seed_cache_from_db(cache, raw)
        print(f"[recetas] recuperadas {recuperados} traducciones ya pagadas", flush=True)
    elif len(cache):
        print(f"[recetas] la caché trae {len(cache)} traducciones de antes", flush=True)

    spend = Spend()

    unique_ingredients = sorted({i.name for r in raw for i in r.ingredients})
    print(f"\n[recetas] traduciendo {len(unique_ingredients)} ingredientes distintos…", flush=True)
    ingredient_es = await translate(
        unique_ingredients, INGREDIENT_PROMPT, BATCH_NAMES, spend, token, cache, "ingredients"
    )

    print(f"\n[recetas] traduciendo {len(raw)} nombres de plato…", flush=True)
    title_es = await translate(
        [r.name for r in raw], TITLE_PROMPT, BATCH_NAMES, spend, token, cache, "titles"
    )

    print("\n[recetas] cargando el catálogo de alimentos…", flush=True)
    index = load_index()
    print(f"[recetas] {len(index.foods)} alimentos genéricos en memoria", flush=True)

    # De aquí en adelante se trabaja y se GUARDA por lotes: traducir los pasos de un lote,
    # guardarlo, y solo entonces pasar al siguiente. Así lo que se ha pagado está en la base
    # de datos desde el minuto siguiente a pagarlo.
    print(f"\n[recetas] traduciendo los pasos y guardando de {SAVE_EVERY} en {SAVE_EVERY}…")
    guardadas = ingredientes = descartadas = 0
    sin_emparejar: set[str] = set()
    for start in range(0, len(raw), SAVE_EVERY):
        lote = raw[start : start + SAVE_EVERY]
        steps_es: dict[str, str] = {}
        if not skip_steps:
            steps_es = await translate(
                [r.instructions for r in lote],
                STEPS_PROMPT,
                BATCH_STEPS,
                spend,
                token,
                cache,
                "steps",
            )
        rows = []
        for recipe in lote:
            row, faltan = build_row(
                recipe, title_es, steps_es, ingredient_es, index, resolve_grams
            )
            sin_emparejar |= faltan
            if row is None:
                descartadas += 1  # sin un solo ingrediente emparejado no se calcula nada
            else:
                rows.append(row)
        if dry_run:
            # Se cuenta lo mismo que se guardaría, para que el ensayo informe de verdad.
            guardadas += len(rows)
            ingredientes += sum(len(r["ingredients"]) for r in rows)
        elif rows:
            recetas_lote, ingredientes_lote = save_recipes(rows)
            guardadas += recetas_lote
            ingredientes += ingredientes_lote
        print(
            f"  {min(start + SAVE_EVERY, len(raw))}/{len(raw)} · {guardadas} guardadas · {spend}",
            flush=True,
        )

    print(f"\n[recetas] {guardadas} recetas con {ingredientes} ingredientes")
    if descartadas:
        print(f"[recetas] {descartadas} descartadas por no emparejar ningún ingrediente")
    if sin_emparejar:
        muestra = ", ".join(sorted(sin_emparejar)[:8])
        print(f"[recetas] {len(sin_emparejar)} ingredientes sin equivalente, p. ej.: {muestra}")

    print(f"\n[recetas] GASTO: {spend}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="no escribe en la base de datos")
    parser.add_argument(
        "--skip-steps", action="store_true", help="no traduce los pasos (lo más caro)"
    )
    parser.add_argument("--limit", type=int, default=None, help="solo las primeras N recetas")
    parser.add_argument(
        "--repair",
        action="store_true",
        help="rehace lo ya importado reutilizando las traducciones que están en la base de datos",
    )
    args = parser.parse_args()
    return asyncio.run(run(args.dry_run, args.skip_steps, args.limit, args.repair))


if __name__ == "__main__":
    raise SystemExit(main())
