"""Armazenamento persistente e criptografado das credenciais do Earth Engine por usuário."""
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

import streamlit as st
from cryptography.fernet import Fernet, InvalidToken

DB_PATH = os.environ.get("DB_PATH", os.path.join("data", "app.db"))


def _get_fernet() -> Fernet:
    key = st.secrets.get("app_encryption_key")
    if not key:
        raise RuntimeError(
            "app_encryption_key não configurado em .streamlit/secrets.toml. "
            "Gere um com: python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_credentials (
                email TEXT PRIMARY KEY,
                encrypted_json BLOB NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def get_credentials(email: str) -> dict | None:
    with closing(sqlite3.connect(DB_PATH)) as conn:
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
    with closing(sqlite3.connect(DB_PATH)) as conn:
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
