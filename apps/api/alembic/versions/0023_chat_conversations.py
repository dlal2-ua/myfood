"""Conversaciones de chat de verdad, y un orden de mensajes que no dependa del reloj.

Dos fallos que venían de origen y se arreglan juntos porque tocan la misma tabla:

1. «Conversación nueva» nunca funcionó. `POST /chat/reset` insertaba un mensaje con
   `role='divider'` contra el CHECK `role IN ('user','assistant')` de la migración 0001, que
   ninguna migración amplió: la petición reventaba con un 500 genérico. En vez de ampliar el
   CHECK se introduce lo que el usuario esperaba desde el principio — conversaciones como
   filas propias, con su historial, a las que se puede volver.

2. El orden de los mensajes se invertía. `created_at` usa `now()`, que en PostgreSQL es
   `transaction_timestamp()`, y el mensaje del usuario y la respuesta del modelo se insertan
   en la MISMA transacción (`chat/flow.py::process_chat_job`): timestamp idéntico al
   microsegundo, `ORDER BY created_at` empatado y el par saliendo al revés. `id` es un uuid4,
   así que tampoco sirve de desempate. `seq` es un contador monótono por tabla: ordenar por él
   es determinista pase lo que pase con los relojes y con las transacciones.

Se aprovecha para añadir 'plate_photo' a los `kind` de `ai_sessions` (registro por foto del
plato), y así no encadenar dos migraciones sobre lo mismo.

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SELF = "current_setting('app.current_user_id', true)::uuid"

_OLD_KINDS = (
    "diet_plan", "plan_review", "supplement_suggestion", "chat_edit",
    "smart_log", "recipe_import", "receipt_scan",
)  # fmt: skip
_NEW_KINDS = (*_OLD_KINDS, "plate_photo")


def upgrade() -> None:
    op.get_bind().exec_driver_sql(f"""
        CREATE TABLE chat_conversations (
          id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          -- Se rellena con las primeras palabras del primer mensaje del usuario: es
          -- determinista y gratis. Titular con la IA costaría una llamada por conversación.
          title           TEXT,
          created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
          last_message_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        -- La conversación activa es la de `last_message_at` más alto: este índice la resuelve
        -- y ordena de paso la lista del selector.
        CREATE INDEX chat_conversations_recent_idx
          ON chat_conversations (user_id, last_message_at DESC);

        ALTER TABLE chat_conversations ENABLE ROW LEVEL SECURITY;
        ALTER TABLE chat_conversations FORCE ROW LEVEL SECURITY;
        CREATE POLICY chat_conversations_isolation ON chat_conversations
          USING (user_id = {_SELF});
    """)

    # Una conversación por usuario con todo lo que ya tenía. No puede haber cortes previos:
    # el `role='divider'` que los marcaba violaba el CHECK, así que nunca se llegó a guardar.
    op.get_bind().exec_driver_sql("""
        INSERT INTO chat_conversations (user_id, title, created_at, last_message_at)
        SELECT m.user_id,
               left((
                 SELECT u.content FROM chat_messages u
                 WHERE u.user_id = m.user_id AND u.role = 'user'
                 ORDER BY u.created_at LIMIT 1
               ), 60),
               min(m.created_at),
               max(m.created_at)
        FROM chat_messages m
        GROUP BY m.user_id;

        ALTER TABLE chat_messages ADD COLUMN conversation_id UUID
          REFERENCES chat_conversations(id) ON DELETE CASCADE;

        UPDATE chat_messages m
        SET conversation_id = c.id
        FROM chat_conversations c
        WHERE c.user_id = m.user_id;

        ALTER TABLE chat_messages ALTER COLUMN conversation_id SET NOT NULL;
    """)

    # `seq` se rellena a mano en vez de con BIGSERIAL: así los mensajes que ya existen quedan
    # en el orden en que se escribieron (`ctid` desempata los pares con el mismo timestamp,
    # y el usuario siempre se insertó antes que el asistente) y no en el que decida el rewrite.
    op.get_bind().exec_driver_sql("""
        ALTER TABLE chat_messages ADD COLUMN seq BIGINT;

        UPDATE chat_messages m
        SET seq = ordered.rn
        FROM (
          SELECT id, row_number() OVER (ORDER BY created_at, ctid) AS rn FROM chat_messages
        ) ordered
        WHERE ordered.id = m.id;

        CREATE SEQUENCE chat_messages_seq_seq OWNED BY chat_messages.seq;
        SELECT setval('chat_messages_seq_seq', coalesce((SELECT max(seq) FROM chat_messages), 0) + 1, false);
        ALTER TABLE chat_messages ALTER COLUMN seq SET DEFAULT nextval('chat_messages_seq_seq');
        ALTER TABLE chat_messages ALTER COLUMN seq SET NOT NULL;

        CREATE INDEX chat_messages_conversation_idx ON chat_messages (conversation_id, seq);
    """)

    op.get_bind().exec_driver_sql("ALTER TABLE ai_sessions DROP CONSTRAINT ai_sessions_kind_check;")
    kinds_sql = ", ".join(f"'{k}'" for k in _NEW_KINDS)
    op.get_bind().exec_driver_sql(f"""
        ALTER TABLE ai_sessions
        ADD CONSTRAINT ai_sessions_kind_check CHECK (kind IN ({kinds_sql}));
    """)


def downgrade() -> None:
    op.get_bind().exec_driver_sql("ALTER TABLE ai_sessions DROP CONSTRAINT ai_sessions_kind_check;")
    kinds_sql = ", ".join(f"'{k}'" for k in _OLD_KINDS)
    op.get_bind().exec_driver_sql(f"""
        DELETE FROM ai_sessions WHERE kind = 'plate_photo';
        ALTER TABLE ai_sessions
        ADD CONSTRAINT ai_sessions_kind_check CHECK (kind IN ({kinds_sql}));

        DROP INDEX IF EXISTS chat_messages_conversation_idx;
        ALTER TABLE chat_messages DROP COLUMN IF EXISTS seq;
        ALTER TABLE chat_messages DROP COLUMN IF EXISTS conversation_id;

        DROP POLICY IF EXISTS chat_conversations_isolation ON chat_conversations;
        DROP TABLE IF EXISTS chat_conversations;
    """)
