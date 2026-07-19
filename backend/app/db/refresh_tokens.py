"""
Descrição da funcionalidade
---------------------------
Persistência dos refresh tokens (tabela nova `refresh_tokens`, ver
db/schema.py) — só o hash SHA-256 é guardado, nunca o valor em claro (esse só
existe no cookie httpOnly do navegador). Suporta rotação (revogar o antigo ao
emitir um novo) e logout (revogar sem emitir).
"""
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from app.core.config import get_settings


def store_refresh_token(token_hash: str, user_email: str, expires_at: datetime) -> None:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        conn.execute(
            """
            INSERT INTO refresh_tokens (token_hash, user_email, created_at, expires_at, revoked_at)
            VALUES (?, ?, ?, ?, NULL)
            """,
            (
                token_hash,
                user_email,
                datetime.now(timezone.utc).isoformat(),
                expires_at.isoformat(),
            ),
        )
        conn.commit()


def get_valid_refresh_token(token_hash: str) -> dict | None:
    """Retorna {user_email, expires_at} se o token existir, não estiver
    revogado e não estiver expirado; None caso contrário (qualquer um desses
    casos é tratado como "refresh inválido" pelo chamador — força novo
    login, igual ao comportamento de um JWT expirado hoje)."""
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        row = conn.execute(
            """
            SELECT user_email, expires_at FROM refresh_tokens
            WHERE token_hash = ? AND revoked_at IS NULL
            """,
            (token_hash,),
        ).fetchone()
    if row is None:
        return None
    user_email, expires_at = row
    if datetime.fromisoformat(expires_at) < datetime.now(timezone.utc):
        return None
    return {"user_email": user_email, "expires_at": expires_at}


def revoke_refresh_token(token_hash: str) -> None:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        conn.execute(
            "UPDATE refresh_tokens SET revoked_at = ? WHERE token_hash = ?",
            (datetime.now(timezone.utc).isoformat(), token_hash),
        )
        conn.commit()


def revoke_all_for_user(user_email: str) -> None:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        conn.execute(
            "UPDATE refresh_tokens SET revoked_at = ? WHERE user_email = ? AND revoked_at IS NULL",
            (datetime.now(timezone.utc).isoformat(), user_email),
        )
        conn.commit()
