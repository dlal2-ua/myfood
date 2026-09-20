"""Origen de cada alérgeno de `food_allergens` (Fase 4/5/8: filtro de alérgenos).

`food_allergens` estaba vacía en producción, así que el filtro de alérgenos no
excluía nada (motor de dietas, validador de iafood, chat, `/similar`). Ahora el
ETL la puebla, y como no todos los datos valen lo mismo se guarda de dónde sale
cada fila:

- `declared`: `allergens_tags` de Open Food Facts (lo que declara el fabricante).
- `trace`: `traces_tags` de OFF ("puede contener"): para quien tiene una alergia
  se trata igual que un alérgeno declarado; la interfaz lo distingue.
- `inferred`: alimentos genéricos (USDA/CIQUAL/BEDCA) sin etiquetas, clasificados
  por palabras clave — orientativo, prefiere errar por exceso (ver
  `etl/transform/allergens.py`).

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("""
        ALTER TABLE food_allergens
          ADD COLUMN origin TEXT NOT NULL DEFAULT 'declared'
          CHECK (origin IN ('declared', 'trace', 'inferred'));
        CREATE INDEX food_allergens_allergen_code_idx ON food_allergens (allergen_code);
    """)


def downgrade() -> None:
    op.get_bind().exec_driver_sql("""
        DROP INDEX IF EXISTS food_allergens_allergen_code_idx;
        ALTER TABLE food_allergens DROP COLUMN origin;
    """)
