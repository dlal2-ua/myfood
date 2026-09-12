"""Job por lotes: calcula y sube a `food_vectors` el vector nutricional
normalizado de cada alimento del catálogo (sección "Alimentos similares
(sustituciones)"). Se ejecuta a mano tras el ETL, o cuando cambian los
datos nutricionales de un alimento existente — es idempotente (upsert por
`food_id`), así que volver a lanzarlo es seguro.

`foods`/`food_nutrients`/`food_vectors` son catálogo global sin `user_id`
(no están en RLS_TABLES, migración 0002), así que basta el rol de
aplicación normal (`SessionLocal`) — no hace falta el rol admin.

## Por qué el vector se interpola como literal SQL en vez de bind param

`asyncpg` no trae un códec para el tipo `vector` de pgvector (eso es lo
que da el paquete opcional `pgvector-python`, que este proyecto no añade
solo para esto — ver README de la sección "Alimentos similares" del PR).
Sin ese códec, pasar el vector como parámetro bind (`:vec`) falla porque
asyncpg no sabe serializar un `str`/`list` de Python al OID de `vector`
que Postgres reporta para ese parámetro.

En su lugar, el literal del vector (`'[0.1,0.2,...]'::vector`) se
interpola directamente en el texto SQL de cada lote, igual que
`db/session.py` ya hace con `app.current_user_id` en `SET LOCAL` cuando
el bind param no es una opción — es seguro aquí por la misma razón: el
valor nunca viene de una petición HTTP ni de texto de usuario, son floats
que este mismo módulo calculó y formateó (`%.6f`, solo dígitos/punto/
signo/corchetes/comas), nunca una cadena arbitraria. `food_id` sí podría
ir de bind param, pero al ir todos los alimentos del catálogo en el mismo
INSERT multi-fila por lote, se interpola también (es un UUID ya validado
leído de la propia BD, nunca de un request).

Uso: `python -m myfood.scripts.build_food_vectors`
"""

import asyncio

from sqlalchemy import text

from myfood.db.session import SessionLocal
from myfood.domain.food_vector import normalize_food_vector

_BATCH_SIZE = 500

_SELECT_SQL = text("""
    SELECT f.id, n.kcal_100g, n.protein_100g, n.fat_100g, n.carbs_100g,
           n.fiber_100g, n.salt_100g
    FROM foods f
    JOIN food_nutrients n ON n.food_id = f.id
    ORDER BY f.id
""")


def _row_literal(food_id, vec: list[float]) -> str:
    vec_str = "[" + ",".join(f"{v:.6f}" for v in vec) + "]"
    return f"('{food_id}'::uuid, '{vec_str}'::vector)"


def _upsert_sql(rows) -> str:
    values = ",\n".join(_row_literal(food_id, vec) for food_id, vec in rows)
    return f"""
        INSERT INTO food_vectors (food_id, vec)
        VALUES
        {values}
        ON CONFLICT (food_id) DO UPDATE SET vec = EXCLUDED.vec
    """


async def build_food_vectors() -> int:
    """Recalcula y sube el vector de todos los alimentos. Devuelve cuántas
    filas se han insertado/actualizado en `food_vectors`."""
    count = 0
    async with SessionLocal() as session:
        # `.all()` fuerza a traer todas las filas antes de empezar a lanzar
        # los INSERTs por lote en la misma sesión.
        rows = (await session.execute(_SELECT_SQL)).all()
        batch: list[tuple[object, list[float]]] = []

        async def flush() -> None:
            nonlocal count
            if not batch:
                return
            await session.execute(text(_upsert_sql(batch)))
            await session.commit()
            count += len(batch)
            batch.clear()

        for row in rows:
            vec = normalize_food_vector(
                kcal_100g=float(row.kcal_100g),
                protein_100g=float(row.protein_100g),
                fat_100g=float(row.fat_100g),
                carbs_100g=float(row.carbs_100g),
                fiber_100g=float(row.fiber_100g) if row.fiber_100g is not None else None,
                salt_100g=float(row.salt_100g) if row.salt_100g is not None else None,
            )
            batch.append((row.id, vec))
            if len(batch) >= _BATCH_SIZE:
                await flush()
        await flush()

    return count


def main() -> None:
    count = asyncio.run(build_food_vectors())
    print(f"food_vectors: {count} filas insertadas/actualizadas.")


if __name__ == "__main__":
    main()
