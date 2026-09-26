"""Nombre corto de cada alimento, para las listas y el diario.

Los nombres de USDA y CIQUAL son fieles a la fuente y, en una pantalla, ilegibles: en el diario
se lee «Huevo, entero, crudo, congelado, sal…» truncado, y «Pollo, pechuga, con piel, crudo»
ocupa dos líneas. 7.200 alimentos pasan de 40 caracteres.

Va en una columna aparte y no reemplazando `name_es` por dos razones: la ficha del alimento
tiene que seguir enseñando el nombre de la fuente —es el que cita la licencia— y porque un
nombre corto se puede rehacer sin haber perdido el original. Lo rellena
`etl/short_names.py`; mientras esté vacío se enseña `name_es`, que es lo que pasaba hasta ahora.

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("ALTER TABLE foods ADD COLUMN name_short TEXT;")


def downgrade() -> None:
    op.get_bind().exec_driver_sql("ALTER TABLE foods DROP COLUMN IF EXISTS name_short;")
