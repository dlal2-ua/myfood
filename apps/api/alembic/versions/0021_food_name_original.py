"""Guarda el nombre tal y como lo publica la fuente antes de traducirlo.

USDA está en inglés y CIQUAL en francés, así que sus alimentos no aparecían buscando en
español: más de diez mil alimentos genéricos con sus datos correctos, invisibles. Al traducir
`name_es` hay que conservar el original — es lo que permite volver atrás, comprobar contra la
fuente y rehacer una traducción mala sin reingerir nada.

`name_en` no vale para eso: en USDA ya lleva el inglés, pero en CIQUAL está vacío y el
original es francés; meterlo ahí sería mentir sobre el idioma.

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("""
        ALTER TABLE foods ADD COLUMN name_original text;
        COMMENT ON COLUMN foods.name_original IS
          'Nombre tal cual lo publica la fuente, cuando name_es es una traducción.';
    """)


def downgrade() -> None:
    op.get_bind().exec_driver_sql("""
        -- Se devuelve el nombre original antes de perder la columna: si no, quedarían
        -- traducciones sin forma de comprobarlas contra la fuente.
        UPDATE foods SET name_es = name_original WHERE name_original IS NOT NULL;
        ALTER TABLE foods DROP COLUMN IF EXISTS name_original;
    """)
