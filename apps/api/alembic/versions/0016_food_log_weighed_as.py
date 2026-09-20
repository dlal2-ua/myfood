"""Peso crudo o cocinado en el registro de comidas (sección 21, factor de cocción).

Cuando un alimento tiene `cooking_yield_factor` (gramos cocido / gramos crudo) el usuario puede
decir que pesó el plato ya cocinado: el backend divide los gramos por el factor y calcula la
nutrición sobre el peso crudo equivalente. `food_log.grams` sigue siendo siempre el peso crudo (la
base de los cálculos); `weighed_as` deja constancia de cómo se pesó y `entered_grams` de lo que el
usuario escribió, para poder mostrar «250 g cocido (≈ 89 g crudo)».

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("""
        ALTER TABLE food_log
          ADD COLUMN weighed_as TEXT NOT NULL DEFAULT 'raw'
            CHECK (weighed_as IN ('raw', 'cooked')),
          ADD COLUMN entered_grams NUMERIC(8,2);
    """)


def downgrade() -> None:
    op.get_bind().exec_driver_sql(
        "ALTER TABLE food_log DROP COLUMN weighed_as, DROP COLUMN entered_grams;"
    )
