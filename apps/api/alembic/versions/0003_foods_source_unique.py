"""Clave de upsert idempotente del ETL (sección 11.2).

`(source, source_id)` identifica un alimento de forma estable entre
reejecuciones del ETL (fdcId de USDA, código de barras de OFF, etc.).
Los alimentos `kind='user'` no tienen `source_id` (se identifican solo por
`id`), por eso el índice excluye `source_id IS NULL`.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("""
    CREATE UNIQUE INDEX foods_source_source_id_idx
      ON foods (source, source_id)
      WHERE source_id IS NOT NULL;
    """)


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP INDEX foods_source_source_id_idx;")
