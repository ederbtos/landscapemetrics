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
from app.db.ana_hidroclimatica import init_ana_hidroclimatica_tables
from app.db.diversity_atlas import init_diversity_atlas_table
from app.db.mapbiomas_stats import init_mapbiomas_stats_table
from app.db.municipios import init_municipios_table
from app.db.prodes import init_prodes_table


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
        # Preferências do Escritório Virtual (Fase 8) — só era criada por
        # `db.py::init_db()` (Streamlit legado), nunca por este init_db do
        # backend. Em `data/app.db` já existente isso passava despercebido
        # (a tabela já estava lá desde o app antigo); um deploy do zero só
        # com o backend nunca a criava, quebrando `GET/POST /api/user/settings`
        # e a exclusão de conta da LGPD (`legacy_db.delete_user_settings`).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_settings (
                user_email TEXT PRIMARY KEY,
                settings_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        
        # LGPD: Trilha de auditoria para o Consentimento (Termos de Uso)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lgpd_consents (
                user_email TEXT NOT NULL,
                term_version TEXT NOT NULL,
                client_ip TEXT NOT NULL,
                user_agent TEXT NOT NULL,
                consent_hash TEXT NOT NULL,
                timestamp_utc TEXT NOT NULL,
                PRIMARY KEY (user_email, term_version)
            )
            """
        )
        conn.commit()

    # Dados de referência nacionais (malha municipal/MapBiomas/PRODES/ANA) —
    # cada módulo cuida da própria tabela, mesma convenção acima.
    init_municipios_table()
    init_mapbiomas_stats_table()
    init_prodes_table()
    init_ana_hidroclimatica_tables()
    init_diversity_atlas_table()
