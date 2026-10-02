"""Platos estimados: su desglose, y poder guardarlos en el catálogo.

El registro por texto y por voz deja de despiezar los platos contra el catálogo: «una
marinera» se estima entera, con el conocimiento general del modelo, y se enseña de qué se
compone (rosquilla, ensaladilla rusa, anchoa). Dos cosas necesitan sitio:

- `food_log.components`: el desglose de lo que se apuntó, tal y como se aceptó, para poder
  enseñarlo en el diario. Es solo descripción; los totales siguen en sus columnas.
- `food_components`: el desglose de un plato que el usuario decide guardar en `foods`
  (`source='ai_estimate'`). La próxima vez que lo nombre se reutiliza esa estimación en vez
  de volver a pedírsela al modelo.

`foods.kind` no cambia: los platos guardados entran como `'user'`, que ya existía, y se
distinguen por `source`. Así no hay que tocar ningún filtro que enumere los `kind`.

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("""
        CREATE TABLE food_components (
          id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          food_id  UUID NOT NULL REFERENCES foods(id) ON DELETE CASCADE,
          position SMALLINT NOT NULL,
          name     TEXT NOT NULL,
          -- De UNA ración del plato. Nulos si el modelo solo nombró el componente.
          grams    NUMERIC(8,2),
          kcal     NUMERIC(9,2)
        );
        CREATE INDEX food_components_food_idx ON food_components (food_id, position);

        -- Los platos estimados se cargan enteros en cada registro por texto: son pocos, pero
        -- `foods` tiene 21.000 filas y sin esto sería un recorrido completo cada vez.
        CREATE INDEX foods_ai_estimate_idx ON foods (created_at) WHERE source = 'ai_estimate';

        ALTER TABLE food_log ADD COLUMN components JSONB;
    """)


def downgrade() -> None:
    op.get_bind().exec_driver_sql("""
        ALTER TABLE food_log DROP COLUMN IF EXISTS components;
        DROP INDEX IF EXISTS foods_ai_estimate_idx;
        DROP TABLE IF EXISTS food_components;
    """)
