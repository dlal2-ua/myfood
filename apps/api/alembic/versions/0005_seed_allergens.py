"""Siembra de los 14 alérgenos regulados (Reglamento UE 1169/2011, Anexo II).

`allergens` es catálogo de referencia global (sin `user_id`, sin RLS) — se
siembra una sola vez aquí, igual que cualquier otro dato de catálogo fijo
que no depende del ETL. Los códigos son los que usa el resto del código
(`routers/restrictions.py`, `food_allergens`); los nombres en español
siguen el texto oficial del Anexo II, abreviado donde la lista de la UE
enumera variedades concretas (p. ej. "frutos de cáscara" sin listar cada
fruto).

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ALLERGENS = [
    ("gluten", "Cereales que contienen gluten y productos derivados"),
    ("crustaceos", "Crustáceos y productos derivados"),
    ("huevos", "Huevos y productos derivados"),
    ("pescado", "Pescado y productos derivados"),
    ("cacahuetes", "Cacahuetes y productos derivados"),
    ("soja", "Soja y productos derivados"),
    ("lacteos", "Leche y sus derivados (incluida la lactosa)"),
    ("frutos_de_cascara", "Frutos de cáscara (almendras, avellanas, nueces, anacardos, "
                           "pistachos, nueces de macadamia, etc.) y productos derivados"),
    ("apio", "Apio y productos derivados"),
    ("mostaza", "Mostaza y productos derivados"),
    ("sesamo", "Granos de sésamo y productos derivados"),
    ("sulfitos", "Dióxido de azufre y sulfitos en concentraciones superiores a 10 mg/kg o 10 mg/l"),
    ("altramuces", "Altramuces y productos derivados"),
    ("moluscos", "Moluscos y productos derivados"),
]


def upgrade() -> None:
    bind = op.get_bind()
    for code, name_es in ALLERGENS:
        bind.execute(
            sa.text(
                "INSERT INTO allergens (code, name_es) VALUES (:code, :name_es) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "name_es": name_es},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for code, _name_es in ALLERGENS:
        bind.execute(sa.text("DELETE FROM allergens WHERE code = :code"), {"code": code})
