"""
Descrição da funcionalidade
---------------------------
Inicialização do schema SQLite — porte direto de `db.py::init_db()` do app
Streamlit original, sem alterar nenhuma tabela/coluna existente. Resolve o
mesmo problema de negócio: `data/app.db` já é produção real (usuários,
credenciais do Earth Engine cifradas, histórico de análises) e não pode
exigir migração manual na virada para o backend novo.

Contexto técnico
-----------------
Sem ORM/framework de migração (igual ao app original) — schema evolui via
`CREATE TABLE IF NOT EXISTS` + `ALTER TABLE` guardado em try/except. A única
tabela nova nesta reescrita é `refresh_tokens` (sessão access+refresh, ver
core/security.py), criada com o mesmo padrão para não quebrar bancos
`data/app.db` já existentes.
"""
import os
import sqlite3
from contextlib import closing

from app.core.config import get_settings


def init_db() -> None:
    db_path = get_settings().db_path
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    with closing(sqlite3.connect(db_path)) as conn:
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS metric_results (
                user_email TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                label TEXT NOT NULL,
                data_source TEXT NOT NULL,
                point_lon REAL,
                point_lat REAL,
                buffer_dist REAL,
                class_metrics_json TEXT NOT NULL,
                landscape_metrics_json TEXT NOT NULL,
                metric_names_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_email, fingerprint)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_metric_results_user
            ON metric_results(user_email, created_at)
            """
        )
        # Colunas adicionadas depois da criação original da tabela (matriz
        # socioecológica/SSE) — mesma lógica de app.py/db.py original: SQLite
        # não tem migração automática, então cada ALTER TABLE é tentado e
        # ignorado se a coluna já existir.
        for column_def in (
            "municipio_codigo TEXT",
            "municipio_nome TEXT",
            "municipio_uf TEXT",
            "ano INTEGER",
        ):
            try:
                conn.execute(f"ALTER TABLE metric_results ADD COLUMN {column_def}")
            except sqlite3.OperationalError:
                pass  # coluna já existe

        # Nova nesta reescrita: sessão access+refresh (ver core/security.py).
        # `email` não é chave estrangeira formal (SQLite/simplicidade, mesmo
        # estilo do restante do schema) mas segue a mesma convenção de
        # `user_credentials`/`metric_results`.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                token_hash TEXT PRIMARY KEY,
                user_email TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user
            ON refresh_tokens(user_email)
            """
        )
        conn.commit()
