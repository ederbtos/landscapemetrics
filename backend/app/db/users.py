"""
Descrição da funcionalidade
---------------------------
Persistência da tabela `users` — porte de `db.py::create_user`/`verify_user`.
Hashing/verificação de senha fica em `core/security.py` (separação
persistência vs. criptografia); este módulo só lê/grava o hash já calculado.
"""
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from app.core.config import get_settings


def create_user(email: str, password_hash: bytes) -> bool:
    """Cria um usuário novo. Retorna False se o e-mail já estiver cadastrado."""
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        try:
            conn.execute(
                "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
                (email, password_hash, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            return False
    return True


def get_password_hash(email: str) -> bytes | None:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE email = ?", (email,)
        ).fetchone()
    return row[0] if row else None


def user_exists(email: str) -> bool:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        row = conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone()
    return row is not None
