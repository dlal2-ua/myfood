"""La suite se niega a correr contra una BD con usuarios reales (`conftest.py`).
Las aserciones son relativas al número de usuarios que ya haya (otros tests pueden
dejar restos durante la sesión)."""

from sqlalchemy import text

from tests.conftest import _real_users_present


def _insert_user(conn, email: str) -> None:
    conn.execute(
        text(
            "INSERT INTO users (id, email, password_hash, display_name) "
            "VALUES (gen_random_uuid(), :email, 'x', 'X')"
        ),
        {"email": email},
    )


def test_test_users_do_not_make_the_database_count_as_real(protect_real_ai_credential):
    engine = protect_real_ai_credential
    if engine is None:
        return
    with engine.begin() as conn:
        before = _real_users_present(conn)
        _insert_user(conn, "guard-test@test.myfood")
        try:
            assert _real_users_present(conn) == before
        finally:
            conn.execute(text("DELETE FROM users WHERE email = 'guard-test@test.myfood'"))


def test_a_normal_looking_user_makes_the_database_count_as_real(protect_real_ai_credential):
    engine = protect_real_ai_credential
    if engine is None:
        return
    with engine.begin() as conn:
        before = _real_users_present(conn)
        _insert_user(conn, "alguien@gmail.com")
        try:
            assert _real_users_present(conn) == before + 1
        finally:
            conn.execute(text("DELETE FROM users WHERE email = 'alguien@gmail.com'"))
