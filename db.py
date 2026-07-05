"""
Descrição da funcionalidade
---------------------------
Persistência das credenciais de conta de serviço do Google Earth Engine, uma
por usuário. Resolve o problema de negócio de eliminar a dependência de uma
única conta de serviço compartilhada (limitada por cota/projeto GCP) — cada
usuário passa a rodar as análises com sua própria cota.

Contexto técnico
-----------------
Camada de acesso a dados do app: SQLite local (arquivo único, sem servidor
de banco separado) em `DB_PATH` (padrão `data/app.db`, path relativo ao
diretório de trabalho do processo — no container é montado como volume via
docker-compose para sobreviver a rebuilds). O e-mail vindo de auth.py é a
chave primária. O JSON da credencial é cifrado em repouso com Fernet
(criptografia simétrica autenticada) antes de tocar o disco. A tabela
`users` guarda as contas do próprio app (login por e-mail/senha, ver
auth.py): senha nunca em texto puro, só o hash bcrypt.

Regras de negócio
------------------
- Cada usuário tem no máximo uma credencial ativa (`INSERT ... ON CONFLICT
  DO UPDATE`): salvar uma nova credencial sempre substitui a anterior, não
  há histórico nem múltiplas contas por usuário.
- A cifra usa uma chave única para todo o app (`app_encryption_key`), não uma
  chave por usuário — qualquer processo com essa chave decifra as credenciais
  de todos os usuários. A chave deve ser tratada com o mesmo cuidado que as
  próprias credenciais do GCP.

Pontos de atenção
------------------
- Perda de `app_encryption_key` torna todas as credenciais salvas
  permanentemente irrecuperáveis (não há mecanismo de rotação de chave ou
  re-criptografia em `save_credentials`).
- `get_credentials` retorna `None` silenciosamente tanto para "usuário nunca
  cadastrou credencial" quanto para "credencial corrompida/chave errada"
  (`InvalidToken`) — do ponto de vista de app.py os dois casos são
  indistinguíveis e levam ao mesmo formulário de cadastro, o que pode
  confundir um usuário que já havia cadastrado credenciais válidas.
- Sem migração de schema: mudanças futuras na tabela exigem lidar com bancos
  `data/app.db` já existentes em produção.

Melhorias sugeridas
---------------------
- Logar (sem vazar o payload) quando `InvalidToken` ocorre, para diferenciar
  "nunca cadastrou" de "credencial corrompida" nos logs de operação.
"""
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

import bcrypt
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                password_hash BLOB NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def create_user(email: str, password: str) -> bool:
    """Cria um usuário novo. Retorna False se o e-mail já estiver cadastrado."""
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    with closing(sqlite3.connect(DB_PATH)) as conn:
        try:
            conn.execute(
                "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
                (email, password_hash, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            return False
    return True


def verify_user(email: str, password: str) -> bool:
    """Confere e-mail/senha contra o hash salvo."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE email = ?", (email,)
        ).fetchone()
    if row is None:
        return False
    return bcrypt.checkpw(password.encode("utf-8"), row[0])


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
        # InvalidToken aqui significa "chave errada/rotacionada" ou "dado
        # corrompido", nunca "usuário não cadastrado" (esse caso já retornou
        # acima). Tratamos como None de propósito para reaproveitar o mesmo
        # formulário de cadastro em app.py, mas isso mascara o problema real
        # do operador do app — ver "Pontos de atenção" no topo do módulo.
        return None
    return json.loads(decrypted.decode("utf-8"))


def save_credentials(email: str, credentials: dict) -> None:
    fernet = _get_fernet()
    encrypted = fernet.encrypt(json.dumps(credentials).encode("utf-8"))
    with closing(sqlite3.connect(DB_PATH)) as conn:
        # Upsert por e-mail: cadastrar uma nova credencial sempre substitui a
        # anterior (sem histórico). Reflete a regra de negócio de "uma
        # credencial GEE ativa por usuário" — ver módulo.
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
