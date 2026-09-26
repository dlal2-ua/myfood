"""Comidas guardadas: un combo con nombre que se apunta de un toque.

Lo que hace que alguien siga apuntando al tercer día no es la IA, es meter su desayuno de
siempre sin volver a buscar cuatro alimentos. Y resuelve además el caso de los platos
compuestos que no están en el catálogo: «bocadillo de sobrasada» no existe como alimento, pero
guardado una vez pasa a ser una sola línea con sus calorías y sus macros.

Los items guardan el snapshot nutricional igual que `food_log` (sección 6.5): repetir una comida
guardada tiene que apuntar exactamente lo mismo que se apuntó la primera vez, aunque el catálogo
haya cambiado. `food_id` puede ser nulo para los platos que el modelo estimó y no existen en
`foods` — misma idea que `food_log.custom_name` (migración 0020).

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SELF = "current_setting('app.current_user_id', true)::uuid"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(f"""
        CREATE TABLE saved_meals (
          id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          name         TEXT NOT NULL,
          -- La comida en la que se suele apuntar, para proponerla por defecto al repetirla.
          meal_type    TEXT CHECK (meal_type IN
                         ('breakfast','morning_snack','lunch','afternoon_snack','dinner','supper')),
          created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
          last_used_at TIMESTAMPTZ,
          -- Cuántas veces se ha apuntado de verdad. Ordena la lista: lo que más repites, arriba.
          use_count    INTEGER NOT NULL DEFAULT 0
        );
        -- Un mismo nombre dos veces solo confunde: al guardar se reemplaza.
        CREATE UNIQUE INDEX saved_meals_name_key ON saved_meals (user_id, lower(name));
        CREATE INDEX saved_meals_recent_idx ON saved_meals (user_id, use_count DESC, last_used_at DESC);

        ALTER TABLE saved_meals ENABLE ROW LEVEL SECURITY;
        ALTER TABLE saved_meals FORCE ROW LEVEL SECURITY;
        CREATE POLICY saved_meals_isolation ON saved_meals USING (user_id = {_SELF});

        CREATE TABLE saved_meal_items (
          id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          saved_meal_id UUID NOT NULL REFERENCES saved_meals(id) ON DELETE CASCADE,
          -- Nulo cuando es un plato estimado que no existe en el catálogo (migración 0020).
          food_id       UUID REFERENCES foods(id),
          custom_name   TEXT,
          grams         NUMERIC(8,2) NOT NULL,
          -- Snapshot congelado, igual que en `food_log`: repetir una comida guardada apunta
          -- exactamente lo mismo que se apuntó la primera vez.
          kcal          NUMERIC(9,2) NOT NULL,
          protein_g     NUMERIC(9,2) NOT NULL,
          fat_g         NUMERIC(9,2) NOT NULL,
          carbs_g       NUMERIC(9,2) NOT NULL,
          micros        JSONB NOT NULL DEFAULT '{{}}'::jsonb,
          CONSTRAINT saved_meal_items_identified
            CHECK ((food_id IS NOT NULL) <> (custom_name IS NOT NULL))
        );
        CREATE INDEX saved_meal_items_meal_idx ON saved_meal_items (saved_meal_id);
    """)

    # En el histórico se distingue lo repetido de lo buscado a mano, que es la mitad de la
    # razón de tener esta función: saber cuánto de lo que comes es «lo de siempre».
    op.get_bind().exec_driver_sql("""
        ALTER TABLE food_log DROP CONSTRAINT IF EXISTS food_log_entry_source_check;
        ALTER TABLE food_log ADD CONSTRAINT food_log_entry_source_check
          CHECK (entry_source IN
            ('manual', 'scan', 'plan', 'recipe', 'chat', 'ai_estimate', 'saved_meal'));
    """)

    # `saved_meal_items` no lleva `user_id`: se filtra por la FK, igual que `supplement_stock`
    # en la migración 0002.
    op.get_bind().exec_driver_sql(f"""
        ALTER TABLE saved_meal_items ENABLE ROW LEVEL SECURITY;
        ALTER TABLE saved_meal_items FORCE ROW LEVEL SECURITY;
        CREATE POLICY saved_meal_items_isolation ON saved_meal_items
          USING (
            saved_meal_id IN (SELECT id FROM saved_meals WHERE user_id = {_SELF})
          );
    """)


def downgrade() -> None:
    op.get_bind().exec_driver_sql("""
        DELETE FROM food_log WHERE entry_source = 'saved_meal';
        ALTER TABLE food_log DROP CONSTRAINT IF EXISTS food_log_entry_source_check;
        ALTER TABLE food_log ADD CONSTRAINT food_log_entry_source_check
          CHECK (entry_source IN ('manual', 'scan', 'plan', 'recipe', 'chat', 'ai_estimate'));

        DROP POLICY IF EXISTS saved_meal_items_isolation ON saved_meal_items;
        DROP TABLE IF EXISTS saved_meal_items;
        DROP POLICY IF EXISTS saved_meals_isolation ON saved_meals;
        DROP TABLE IF EXISTS saved_meals;
    """)
