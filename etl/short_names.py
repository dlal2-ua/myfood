"""Nombre corto de cada alimento, para las listas y el diario.

Los nombres de USDA y CIQUAL son fieles a la fuente y, en una pantalla, ilegibles: en el diario
se lee «Huevo, entero, crudo, congelado, sal…» truncado, y «Pollo, pechuga, con piel, crudo»
ocupa dos líneas. 7.200 alimentos pasan de 40 caracteres.

Cortar por la primera coma no sirve: «Pollo, pechuga, con piel, crudo» se quedaría en «Pollo» y
se perdería justo lo que distingue una pechuga de un muslo. Por eso lo hace el modelo — tiene
que decidir qué parte del nombre es la que identifica el alimento.

Solo se toca el NOMBRE, y en una columna aparte: `name_es` sigue siendo el de la fuente y es lo
que se enseña en la ficha. Ni una caloría ni un macro se recalculan (R1).

    python -m etl.short_names --limit 200        # una tanda de prueba
    python -m etl.short_names --dry-run          # enseña los nombres sin guardar
    python -m etl.short_names                    # todo lo que quede
    python -m etl.short_names --revert           # borra todos los nombres cortos

Es reanudable: se salta lo que ya tiene `name_short`, así que se puede cortar y seguir.
Al terminar hay que reindexar Meilisearch (`python -m etl.index`).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

from etl.db import get_connection


def _api_imports():
    """Igual que en `translate_names`: el SDK de Claude se carga al ejecutar, no al importar,
    para que el módulo y sus tests se puedan cargar fuera del contenedor de la API."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api", "src"))
    from myfood.ai.agent import AiAgentError, run_agent
    from myfood.ai.client import get_decrypted_token
    from myfood.db.session import AdminSessionLocal

    return AiAgentError, run_agent, get_decrypted_token, AdminSessionLocal


# Lotes de 25 y no de 40 como la traducción: aquí se va de los nombres más largos a los
# más cortos, así que los primeros lotes son el peor caso y con 40 se pasaban de tiempo.
BATCH_SIZE = 25
# Holgado a propósito: un lote de 25 nombres largos tarda de 2 a 5 minutos, y más cuando
# hay varios a la vez. Con 180 s se caía la mitad por tiempo, y un lote caído es cuota
# gastada para nada.
TIMEOUT_SECONDS = 420.0
# En serie son 12.000 alimentos a un lote cada tres minutos: más de un día. Cada lote es
# una llamada independiente —no comparten nada— así que van en paralelo.
DEFAULT_WORKERS = 6
# Lo que cabe en una línea de una lista en un móvil sin truncarse.
MAX_SHORT_CHARS = 42
# Por debajo de esto no hay nada que acortar.
MIN_LONG_CHARS = 25

SYSTEM_PROMPT = """Acortas nombres de alimentos de tablas oficiales de composición para que
quepan en una lista de una app, en un móvil.

El nombre largo tiene la nomenclatura de la tabla: alimento, parte, variedad, estado y
preparación, separados por comas. Tu trabajo es dejar lo que identifica al alimento para alguien
que lo está buscando, en el orden natural del español.

Reglas:
- Como mucho 42 caracteres. Cuanto más corto mejor, sin dejar de distinguirlo.
- Conserva lo que lo distingue de sus vecinos en la tabla: la parte (pechuga, muslo, solomillo),
  la variedad (integral, desnatado, virgen extra) y la preparación cuando cambia el alimento
  (crudo, cocido, frito, en conserva).
- Tira lo que no distingue nada en una lista: «enriquecido», «pasteurizado», «comercial»,
  «preparado», «sin sal añadida», los códigos y las coletillas de la fuente.
- Dale la vuelta a la nomenclatura de tabla: «Pollo, pechuga, cruda» es «Pechuga de pollo
  cruda», no «Pollo pechuga cruda».
- Empieza por mayúscula y no acabes en punto.
- Conserva las marcas y los nombres propios tal cual.
- Si el nombre ya es corto y se lee bien, devuélvelo igual.

Ejemplos:
  «Huevo, entero, crudo, congelado, salado, pasteurizado» -> «Huevo entero congelado»
  «Pollo, pechuga, con piel, crudo» -> «Pechuga de pollo con piel, cruda»
  «Arroz blanco, grano largo, regular, crudo, enriquecido» -> «Arroz blanco de grano largo»
  «Plátano macho, verde, frito» -> «Plátano macho frito»

Responde SOLO con un array JSON de strings, en el mismo orden y con el mismo número de
elementos que la entrada. Sin texto alrededor, sin markdown."""


def build_prompt(names: list[str]) -> str:
    listado = json.dumps(names, ensure_ascii=False, indent=0)
    return f"Acorta estos {len(names)} nombres de alimentos:\n{listado}"


def parse_response(text: str, expected: int) -> list[str] | None:
    """Devuelve la lista solo si cuadra. Un lote que no cuadra se descarta entero: emparejar
    mal los nombres pondría a un alimento el nombre corto de otro, que es peor que dejarlo
    largo."""
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
    out = []
    for item in parsed:
        if not isinstance(item, str) or not item.strip():
            return None
        short = " ".join(item.split())
        # Un «nombre corto» más largo que el original no es un nombre corto. Se descarta el
        # lote entero por lo mismo que arriba: mejor sin acortar que mal emparejado.
        if len(short) > MAX_SHORT_CHARS:
            return None
        out.append(short)
    return out


def pending(limit: int | None) -> list[tuple[str, str]]:
    """`(id, nombre)` de lo que queda por acortar, lo más largo primero — que es lo que peor
    se lee y lo que más se nota arreglado."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id::text, name_es FROM foods
            WHERE name_short IS NULL AND length(name_es) > %s
            ORDER BY length(name_es) DESC
            """
            + (" LIMIT %s" if limit else ""),
            (MIN_LONG_CHARS, limit) if limit else (MIN_LONG_CHARS,),
        )
        return [(row[0], row[1]) for row in cur.fetchall()]


def save(pairs: list[tuple[str, str]]) -> int:
    """`(id, nombre corto)`. No se toca `name_es`: el nombre de la fuente sigue siendo el que
    se enseña en la ficha del alimento y el que cita la licencia."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.executemany(
            "UPDATE foods SET name_short = %s WHERE id = %s AND name_short IS NULL",
            [(short, food_id) for food_id, short in pairs],
        )
        conn.commit()
        return cur.rowcount if cur.rowcount and cur.rowcount > 0 else len(pairs)


def revert() -> int:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE foods SET name_short = NULL WHERE name_short IS NOT NULL")
        conn.commit()
        return cur.rowcount


async def shorten_all(limit: int | None, dry_run: bool, workers: int = DEFAULT_WORKERS) -> int:
    AiAgentError, run_agent, get_decrypted_token, AdminSessionLocal = _api_imports()

    async with AdminSessionLocal() as session:
        token = await get_decrypted_token(session)
    if token is None:
        print("No hay credencial de iafood configurada.", file=sys.stderr)
        return 1

    rows = pending(limit)
    if not rows:
        print("[acortar] no queda nada por acortar")
        return 0
    print(
        f"[acortar] {len(rows)} alimentos pendientes, en lotes de {BATCH_SIZE} y {workers} a la vez"
    )

    lotes = [rows[i : i + BATCH_SIZE] for i in range(0, len(rows), BATCH_SIZE)]
    progreso = {"done": 0, "failed": 0}
    started = time.monotonic()
    semaforo = asyncio.Semaphore(workers)

    async def procesar(numero: int, batch: list[tuple[str, str]]) -> None:
        names = [name for _id, name in batch]
        async with semaforo:
            try:
                result = await run_agent(
                    token=token,
                    prompt=build_prompt(names),
                    system_prompt=SYSTEM_PROMPT,
                    timeout_seconds=TIMEOUT_SECONDS,
                )
            except AiAgentError as exc:
                progreso["failed"] += len(batch)
                print(f"[acortar] lote {numero}: falló ({exc})", flush=True)
                return

        shortened = parse_response(result.text, len(batch))
        if shortened is None:
            progreso["failed"] += len(batch)
            print(
                f"[acortar] lote {numero}: respuesta descartada (no cuadra con la entrada)",
                flush=True,
            )
            return

        if dry_run:
            for original, nuevo in zip(names, shortened, strict=True):
                print(f"  {original}\n    -> {nuevo}")
        else:
            # `save` es psycopg2 sincrónico: se saca del bucle para no bloquearlo mientras
            # los otros lotes esperan al modelo.
            await asyncio.to_thread(
                save,
                [
                    (food_id, nuevo)
                    for (food_id, _original), nuevo in zip(batch, shortened, strict=True)
                ],
            )
        progreso["done"] += len(batch)
        elapsed = time.monotonic() - started
        ritmo = progreso["done"] / elapsed if elapsed else 0
        quedan = (len(rows) - progreso["done"]) / ritmo / 60 if ritmo else 0
        print(
            f"[acortar] {progreso['done']}/{len(rows)} · {progreso['failed']} fallidos · "
            f"quedan ~{quedan:.0f} min",
            flush=True,
        )

    await asyncio.gather(*(procesar(i + 1, b) for i, b in enumerate(lotes)))
    done, failed = progreso["done"], progreso["failed"]
    print(f"[acortar] terminado: {done} acortados, {failed} sin acortar")
    if not dry_run and done:
        print("[acortar] ahora hay que reindexar: python -m etl.index")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="cuántos alimentos como mucho")
    parser.add_argument("--dry-run", action="store_true", help="enseña los nombres sin guardar")
    parser.add_argument("--revert", action="store_true", help="borra todos los nombres cortos")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="lotes a la vez")
    args = parser.parse_args()

    if args.revert:
        print(f"[acortar] {revert()} nombres cortos borrados")
        return 0
    return asyncio.run(shorten_all(args.limit, args.dry_run, max(1, args.workers)))


if __name__ == "__main__":
    raise SystemExit(main())
