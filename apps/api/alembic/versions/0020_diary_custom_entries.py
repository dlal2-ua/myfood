"""Entradas del diario que no son un alimento del catálogo.

El chat puede apuntar un plato compuesto («tostada de tomate con queso manchego»)
descomponiéndolo en ingredientes reales. Cuando alguno no está en el catálogo, sus valores los
pone el modelo, y entonces la entrada no tiene `food_id`: hace falta un nombre para poder
enseñarla, y una marca para que se vea siempre que ese número no viene de un dato oficial.

La marca va en `entry_source` (`ai_estimate`), que ya existía como texto libre con
`'manual'` por defecto.

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("""
        ALTER TABLE food_log ADD COLUMN custom_name text;

        -- Hasta ahora una entrada era o un alimento del catálogo o una receta, exactamente
        -- una de las dos. Ahora hay un tercer caso: un ingrediente que el modelo estimó y que
        -- no existe en el catálogo, que se identifica por su nombre. Sigue siendo
        -- exactamente UNA de las tres: sin eso, una entrada podría no tener cómo llamarse.
        ALTER TABLE food_log DROP CONSTRAINT IF EXISTS food_log_check;
        ALTER TABLE food_log ADD CONSTRAINT food_log_identified CHECK (
          (food_id IS NOT NULL)::int
          + (recipe_id IS NOT NULL)::int
          + (custom_name IS NOT NULL)::int = 1
        );

        -- `entry_source` estaba acotado a los orígenes que existían entonces; ahora también
        -- se apunta desde el chat, y lo que el modelo estima se distingue del resto.
        ALTER TABLE food_log DROP CONSTRAINT IF EXISTS food_log_entry_source_check;
        ALTER TABLE food_log ADD CONSTRAINT food_log_entry_source_check
          CHECK (entry_source IN ('manual', 'scan', 'plan', 'recipe', 'chat', 'ai_estimate'));
    """)


def downgrade() -> None:
    op.get_bind().exec_driver_sql("""
        ALTER TABLE food_log DROP CONSTRAINT IF EXISTS food_log_entry_source_check;
        ALTER TABLE food_log ADD CONSTRAINT food_log_entry_source_check
          CHECK (entry_source IN ('manual', 'scan', 'plan', 'recipe'));
        ALTER TABLE food_log DROP CONSTRAINT IF EXISTS food_log_identified;
        DELETE FROM food_log WHERE food_id IS NULL AND recipe_id IS NULL;
        ALTER TABLE food_log ADD CONSTRAINT food_log_check
          CHECK ((food_id IS NULL) <> (recipe_id IS NULL));
        ALTER TABLE food_log DROP COLUMN IF EXISTS custom_name;
    """)
