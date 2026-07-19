"""
Descrição da funcionalidade
---------------------------
Persistência das credenciais de conta de serviço do Google Earth Engine, uma
por usuário — porte de `db.py::get_credentials`/`save_credentials`, sem
mudança de schema/comportamento (mesma tabela `user_credentials`, mesma
cifragem Fernet com `app_encryption_key`, mesma regra de "uma credencial
ativa por usuário" via upsert).

Pontos de atenção (herdados do módulo original, ver ROADMAP.md/db.py)
------------------------------------------------------------------------
- Perda de `app_encryption_key` torna todas as credenciais salvas
  permanentemente irrecuperáveis.
- `get_credentials` retorna `None` tanto para "nunca cadastrou" quanto para
  "credencial corrompida/chave errada" (`InvalidToken`) — mesma limitação de
  antes, não resolvida nesta reescrita.
"""
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


def _get_fernet() -> Fernet:
    key = get_settings().app_encryption_key
    return Fernet(key.encode() if isinstance(key, str) else key)


def get_credentials(email: str) -> dict | None:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        row = conn.execute(
            "SELECT encrypted_json FROM user_credentials WHERE email = ?", (email,)
        ).fetchone()
    if row is None:
        return None
    fernet = _get_fernet()
    try:
        decrypted = fernet.decrypt(row[0])
    except InvalidToken:
        return None
    return json.loads(decrypted.decode("utf-8"))


def save_credentials(email: str, credentials: dict) -> None:
    fernet = _get_fernet()
    encrypted = fernet.encrypt(json.dumps(credentials).encode("utf-8"))
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        conn.execute(
            """
            INSERT INTO user_credentials (email, encrypted_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                encrypted_json = excluded.encrypted_json,
                updated_at = excluded.updated_at
            """,
            (email, encrypted, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
