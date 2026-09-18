"""Modo familia (Fase 7, documento 1: "perfiles separados bajo la misma
instancia" + despensa/lista de la compra compartidas).

Nuevas tablas `households` (hogar) y `household_members` (pertenencia,
un usuario en como mucho un hogar a la vez). La despensa pasa a ser
VISIBLE para todo el hogar pero solo MODIFICABLE por su propio dueño
("mi despensa", control individual); la lista de la compra pasa a ser
de verdad colaborativa (visible Y editable/borrable por cualquier
miembro — es una lista de tareas compartida). El resto de tablas
(perfil, medidas, registro diario, planes...) siguen estrictamente
privadas, sin tocar — el modo familia no las pedía.

`my_household_ids()` es SECURITY DEFINER a propósito: una política RLS de
`household_members` que consultara `household_members` DIRECTAMENTE
revienta con "infinite recursion detected in policy" (limitación real y
documentada de Postgres, comprobada en la práctica al escribir esta
migración) — una función SECURITY DEFINER, propiedad del rol que la crea
(el superusuario de las migraciones, que ignora RLS), resuelve "mis
household_id" sin pasar otra vez por la política de la que depende.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SELF = "current_setting('app.current_user_id', true)::uuid"


def upgrade() -> None:
    op.get_bind().exec_driver_sql("""
        CREATE TABLE households (
          id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          name        TEXT NOT NULL,
          invite_code TEXT NOT NULL UNIQUE,
          created_by  UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE household_members (
          household_id UUID NOT NULL REFERENCES households(id) ON DELETE CASCADE,
          user_id      UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
          joined_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ON household_members (household_id);
    """)

    op.get_bind().exec_driver_sql(f"""
        CREATE FUNCTION my_household_ids() RETURNS SETOF UUID
        LANGUAGE sql SECURITY DEFINER STABLE AS $$
          SELECT household_id FROM household_members WHERE user_id = {_SELF}
        $$;
    """)

    op.get_bind().exec_driver_sql(f"""
        ALTER TABLE households ENABLE ROW LEVEL SECURITY;
        ALTER TABLE households FORCE ROW LEVEL SECURITY;
        -- SELECT aparte de INSERT a propósito: al crear un hogar, su fila
        -- todavía no tiene ningún miembro (la de household_members se
        -- inserta justo después, en la misma transacción) — exigir
        -- "id IN mis hogares" también para el INSERT sería una
        -- imposibilidad circular. El INSERT solo exige que quede
        -- atribuido a quien lo crea. `OR created_by = self` en el SELECT
        -- hace falta además por un motivo menos obvio: un INSERT con
        -- RETURNING (el ORM lo añade solo, para leer created_at) hace que
        -- Postgres también compruebe la política de SELECT sobre la fila
        -- recién insertada — sin este OR, crear un hogar fallaba porque
        -- todavía no había ninguna fila en household_members en ese
        -- instante exacto (encontrado en la práctica al escribir esta
        -- migración, no es una precaución teórica).
        CREATE POLICY households_select ON households FOR SELECT
          USING (id IN (SELECT my_household_ids()) OR created_by = {_SELF});
        CREATE POLICY households_insert ON households FOR INSERT
          WITH CHECK (created_by = {_SELF});

        ALTER TABLE household_members ENABLE ROW LEVEL SECURITY;
        ALTER TABLE household_members FORCE ROW LEVEL SECURITY;
        CREATE POLICY household_members_isolation ON household_members
          USING (
            user_id = {_SELF}
            OR household_id IN (SELECT my_household_ids())
          );
    """)

    _household_or_self = f"""
        user_id = {_SELF}
        OR user_id IN (
          SELECT user_id FROM household_members
          WHERE household_id IN (SELECT my_household_ids())
        )
    """

    # Despensa: visible al hogar entero, pero cada uno sigue siendo dueño
    # solo de lo que añade él mismo.
    op.get_bind().exec_driver_sql(f"""
        DROP POLICY IF EXISTS pantry_items_isolation ON pantry_items;
        CREATE POLICY pantry_items_select ON pantry_items FOR SELECT
          USING ({_household_or_self});
        CREATE POLICY pantry_items_insert ON pantry_items FOR INSERT
          WITH CHECK (user_id = {_SELF});
        CREATE POLICY pantry_items_update ON pantry_items FOR UPDATE
          USING (user_id = {_SELF}) WITH CHECK (user_id = {_SELF});
        CREATE POLICY pantry_items_delete ON pantry_items FOR DELETE
          USING (user_id = {_SELF});
    """)

    # Lista de la compra: de verdad colaborativa — cualquier miembro del
    # hogar puede marcar como comprado o quitar lo que haya añadido
    # cualquier otro. Solo crear un artículo sigue exigiendo que quede
    # atribuido a quien lo añade, no a otro miembro en su nombre.
    op.get_bind().exec_driver_sql(f"""
        DROP POLICY IF EXISTS shopping_list_items_isolation ON shopping_list_items;
        CREATE POLICY shopping_list_items_select ON shopping_list_items FOR SELECT
          USING ({_household_or_self});
        CREATE POLICY shopping_list_items_insert ON shopping_list_items FOR INSERT
          WITH CHECK (user_id = {_SELF});
        CREATE POLICY shopping_list_items_update ON shopping_list_items FOR UPDATE
          USING ({_household_or_self}) WITH CHECK ({_household_or_self});
        CREATE POLICY shopping_list_items_delete ON shopping_list_items FOR DELETE
          USING ({_household_or_self});
    """)


def downgrade() -> None:
    for table in ("pantry_items", "shopping_list_items"):
        op.get_bind().exec_driver_sql(f"""
            DROP POLICY IF EXISTS {table}_select ON {table};
            DROP POLICY IF EXISTS {table}_insert ON {table};
            DROP POLICY IF EXISTS {table}_update ON {table};
            DROP POLICY IF EXISTS {table}_delete ON {table};
            CREATE POLICY {table}_isolation ON {table}
              USING (user_id = {_SELF});
        """)

    op.get_bind().exec_driver_sql("""
        DROP TABLE households CASCADE;
        DROP TABLE household_members CASCADE;
        DROP FUNCTION my_household_ids();
    """)
