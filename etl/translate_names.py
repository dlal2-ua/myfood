"""Traduce al español los nombres de los alimentos genéricos de USDA y CIQUAL.

USDA publica en inglés y CIQUAL en francés, así que sus alimentos no aparecen buscando en
español: más de diez mil alimentos con datos correctos, invisibles para el buscador. Solo se
toca el NOMBRE — ni una caloría ni un macro se recalculan (R1): los números siguen siendo los
de la fuente.

No es una traducción literal. «Beans, kidney, red, mature seeds, cooked, boiled, without salt»
tiene la nomenclatura del USDA dentro (alimento, variedad, estado, preparación); en español eso
es «Alubia roja, seca, cocida, sin sal». Por eso lo hace el modelo y no una tabla.

    python -m etl.translate_names --limit 200        # una tanda de prueba
    python -m etl.translate_names                    # todo lo que quede
    python -m etl.translate_names --revert           # deshace: vuelve al nombre original

Es reanudable: se salta lo que ya tiene `name_original`, así que se puede cortar y seguir.
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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api", "src"))

from myfood.ai.agent import AiAgentError, run_agent  # noqa: E402
from myfood.ai.client import get_decrypted_token  # noqa: E402
from myfood.db.session import AdminSessionLocal  # noqa: E402

SOURCES = ("usda_sr", "usda_foundation", "ciqual")
BATCH_SIZE = 40
# Un lote de 40 nombres son unas 2.000 palabras de ida y vuelta: sobra con este margen.
TIMEOUT_SECONDS = 120.0
MAX_NAME_CHARS = 200

SYSTEM_PROMPT = """Traduces al español nombres de alimentos de tablas oficiales de composición
(USDA, en inglés; CIQUAL, en francés).

Son nombres técnicos con una estructura fija: alimento, variedad, estado y preparación,
separados por comas. Mantén esa estructura en español, con el alimento primero.

Reglas:
- Usa el nombre español de uso corriente en España: «alubia» y no «frijol», «gambas» y no
  «camarones», «patata» y no «papa», «zumo» y no «jugo», «maíz» y no «elote».
- Conserva todos los matices: crudo, cocido, hervido, al horno, en conserva, escurrido, sin
  sal, desnatado, enriquecido. Son los que distinguen un alimento de otro en la tabla.
- Conserva los nombres propios y las marcas tal cual (Pont l'Évêque, Kraft, Pillsbury).
- No añadas nada que no esté: ni cantidades, ni calorías, ni explicaciones.
- Si un nombre ya está en español, devuélvelo igual.

Responde SOLO con un array JSON de strings, en el mismo orden y con el mismo número de
elementos que la entrada. Sin texto alrededor, sin markdown."""


def build_prompt(names: list[str]) -> str:
    listado = json.dumps(names, ensure_ascii=False, indent=0)
    return f"Traduce estos {len(names)} nombres de alimentos al español:\n{listado}"


def parse_response(text: str, expected: int) -> list[str] | None:
    """Devuelve la lista solo si cuadra. Un lote que no cuadra se descarta entero: emparejar
    mal las traducciones renombraría alimentos con el nombre de otro, que es peor que dejarlos
    en inglés."""
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
        if not isinstance(item, str) or not item.strip() or len(item) > MAX_NAME_CHARS:
            return None
        out.append(item.strip())
    return out


def pending(limit: int | None) -> list[tuple[str, str]]:
    """`(id, nombre)` de lo que queda por traducir, de las fuentes más usadas primero."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id::text, name_es FROM foods
            WHERE source = ANY(%s) AND name_original IS NULL
            ORDER BY source, name_es
            """
            + (" LIMIT %s" if limit else ""),
            ([*SOURCES], limit) if limit else ([*SOURCES],),
        )
        return [(row[0], row[1]) for row in cur.fetchall()]


def save(pairs: list[tuple[str, str, str]]) -> int:
    """`(id, original, traducción)`. El original se guarda en el mismo UPDATE que el nombre
    nuevo: si se guardara después, una caída dejaría traducciones sin forma de comprobarlas."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.executemany(
            "UPDATE foods SET name_original = %s, name_es = %s WHERE id = %s AND "
            "name_original IS NULL",
            [(original, traducido, food_id) for food_id, original, traducido in pairs],
        )
        conn.commit()
        return cur.rowcount if cur.rowcount and cur.rowcount > 0 else len(pairs)


def revert() -> int:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE foods SET name_es = name_original, name_original = NULL "
            "WHERE name_original IS NOT NULL"
        )
        conn.commit()
        return cur.rowcount


async def translate_all(limit: int | None, dry_run: bool) -> int:
    async with AdminSessionLocal() as session:
        token = await get_decrypted_token(session)
    if token is None:
        print("No hay credencial de iafood configurada.", file=sys.stderr)
        return 1

    rows = pending(limit)
    if not rows:
        print("[traducir] no queda nada por traducir")
        return 0
    print(f"[traducir] {len(rows)} alimentos pendientes, en lotes de {BATCH_SIZE}")

    done = failed = 0
    started = time.monotonic()
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start : start + BATCH_SIZE]
        names = [name for _id, name in batch]
        try:
            result = await run_agent(
                token=token,
                prompt=build_prompt(names),
                system_prompt=SYSTEM_PROMPT,
                timeout_seconds=TIMEOUT_SECONDS,
            )
        except AiAgentError as exc:
            failed += len(batch)
            print(f"[traducir] lote {start // BATCH_SIZE + 1}: falló ({exc})", flush=True)
            continue

        translated = parse_response(result.text, len(batch))
        if translated is None:
            failed += len(batch)
            print(
                f"[traducir] lote {start // BATCH_SIZE + 1}: respuesta descartada "
                "(no cuadra con la entrada)",
                flush=True,
            )
            continue

        if dry_run:
            for original, nuevo in zip(names, translated, strict=True):
                print(f"  {original}\n    -> {nuevo}")
        else:
            save(
                [
                    (food_id, original, nuevo)
                    for (food_id, original), nuevo in zip(batch, translated, strict=True)
                ]
            )
        done += len(batch)
        elapsed = time.monotonic() - started
        ritmo = done / elapsed if elapsed else 0
        quedan = (len(rows) - done) / ritmo / 60 if ritmo else 0
        print(
            f"[traducir] {done}/{len(rows)} · {failed} fallidos · "
            f"quedan ~{quedan:.0f} min",
            flush=True,
        )

    print(f"[traducir] terminado: {done} traducidos, {failed} sin traducir")
    if not dry_run and done:
        print("[traducir] ahora hay que reindexar: python -m etl.index")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="cuántos alimentos como mucho")
    parser.add_argument(
        "--dry-run", action="store_true", help="enseña las traducciones sin guardar"
    )
    parser.add_argument("--revert", action="store_true", help="deshace todas las traducciones")
    args = parser.parse_args()

    if args.revert:
        print(f"[traducir] revertidos {revert()} nombres a su original")
        return 0
    return asyncio.run(translate_all(args.limit, args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
