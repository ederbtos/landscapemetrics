"""
Módulo de Banco de Dados (SQLite e PostgreSQL)
----------------------------------------------
Gerencia a persistência das contas de usuários, credenciais do Google Earth Engine
criptografadas com Fernet e o histórico de análises da Matriz Socioecológica (SSE),
garantindo o isolamento completo por usuário (Escritório Virtual).

Suporta nativamente:
1. PostgreSQL (quando DATABASE_URL ou st.secrets["database_url"] está configurado)
2. SQLite (fallback automático em data/app.db para desenvolvimento/testes locais)
"""
import io
import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

import bcrypt
import pandas as pd
import streamlit as st
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", os.path.join("data", "app.db"))


def _get_fernet() -> Fernet:
    key = None
    if hasattr(st, "secrets") and st.secrets and "app_encryption_key" in st.secrets:
        key = st.secrets["app_encryption_key"]
    if not key:
        key = os.environ.get("APP_ENCRYPTION_KEY")
    if not key:
        # Chave padrão de desenvolvimento se nenhuma for fornecida
        key = "dGVzdF9rZXlfZGV2X29ubHlfZm9yX2xvY2FsX3VzZV8xMjM0NQ=="
    return Fernet(key.encode() if isinstance(key, str) else key)


def _get_db_url() -> Optional[str]:
    """Retorna a URL do banco PostgreSQL se configurada em ambiente ou secrets."""
    url = os.environ.get("DATABASE_URL")
    if not url and hasattr(st, "secrets") and st.secrets:
        url = st.secrets.get("database_url")
        if not url and "database" in st.secrets and isinstance(st.secrets["database"], dict):
            url = st.secrets["database"].get("url")
    return url


@contextmanager
def get_db():
    """Context manager que fornece uma conexão e cursor adaptados para SQLite ou PostgreSQL."""
    db_url = _get_db_url()

    if db_url and (db_url.startswith("postgresql://") or db_url.startswith("postgres://")):
        try:
            import psycopg2
            import psycopg2.extras
            conn = psycopg2.connect(db_url)
            cursor = conn.cursor()
            yield ("postgres", conn, cursor)
            conn.commit()
            cursor.close()
            conn.close()
            return
        except Exception as err:
            logger.warning(f"Falha ao conectar ao PostgreSQL ({err}). Recuando para SQLite...")

    # Fallback para SQLite local
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        yield ("sqlite", conn, cursor)
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def _adapt_query(query: str, db_type: str) -> str:
    """Adapta marcadores de posição de parâmetro: '?' para SQLite, '%s' para PostgreSQL."""
    if db_type == "postgres":
        return query.replace("?", "%s")
    return query


def init_db() -> None:
    """Inicializa as tabelas do banco de dados (users, user_credentials, metric_results)."""
    with get_db() as (db_type, conn, cursor):
        blob_type = "BYTEA" if db_type == "postgres" else "BLOB"
        real_type = "DOUBLE PRECISION" if db_type == "postgres" else "REAL"

        # 1. Tabela de Credenciais GEE do Usuário
        cursor.execute(
            _adapt_query(
                f"""
                CREATE TABLE IF NOT EXISTS user_credentials (
                    email VARCHAR(255) PRIMARY KEY,
                    encrypted_json {blob_type} NOT NULL,
                    updated_at VARCHAR(255) NOT NULL
                )
                """,
                db_type,
            )
        )

        # 2. Tabela de Usuários (Login / Autenticação)
        cursor.execute(
            _adapt_query(
                f"""
                CREATE TABLE IF NOT EXISTS users (
                    email VARCHAR(255) PRIMARY KEY,
                    password_hash {blob_type} NOT NULL,
                    created_at VARCHAR(255) NOT NULL
                )
                """,
                db_type,
            )
        )

        # 3. Tabela de Resultados de Métricas da Paisagem (Escritório Virtual por usuário)
        cursor.execute(
            _adapt_query(
                f"""
                CREATE TABLE IF NOT EXISTS metric_results (
                    user_email VARCHAR(255) NOT NULL,
                    fingerprint VARCHAR(255) NOT NULL,
                    label VARCHAR(255) NOT NULL,
                    data_source VARCHAR(255) NOT NULL,
                    point_lon {real_type},
                    point_lat {real_type},
                    buffer_dist {real_type},
                    class_metrics_json TEXT NOT NULL,
                    landscape_metrics_json TEXT NOT NULL,
                    metric_names_json TEXT NOT NULL,
                    created_at VARCHAR(255) NOT NULL,
                    municipio_codigo VARCHAR(50),
                    municipio_nome VARCHAR(255),
                    municipio_uf VARCHAR(10),
                    ano INTEGER,
                    PRIMARY KEY (user_email, fingerprint)
                )
                """,
                db_type,
            )
        )

        # Índice para consultas rápidas no Escritório Virtual do usuário
        if db_type == "sqlite":
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_metric_results_user ON metric_results(user_email, created_at)"
            )
        else:
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_metric_results_user ON metric_results(user_email, created_at DESC)"
            )

        # Garantir colunas adicionais para bancos existentes
        for col_name, col_type in [
            ("municipio_codigo", "VARCHAR(50)"),
            ("municipio_nome", "VARCHAR(255)"),
            ("municipio_uf", "VARCHAR(10)"),
            ("ano", "INTEGER"),
        ]:
            try:
                cursor.execute(f"ALTER TABLE metric_results ADD COLUMN {col_name} {col_type}")
            except Exception:
                pass

        # 4. Tabela de Configurações e Preferências por Usuário
        cursor.execute(
            _adapt_query(
                """
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_email VARCHAR(255) PRIMARY KEY,
                    settings_json TEXT NOT NULL,
                    updated_at VARCHAR(255) NOT NULL
                )
                """,
                db_type,
            )
        )



def save_metric_result(
    user_email: str,
    fingerprint: str,
    label: str,
    data_source: str,
    point_lonlat: Optional[Tuple[float, float]],
    buffer_dist: Optional[float],
    class_metrics_df: pd.DataFrame,
    landscape_metrics: dict,
    municipio_codigo: Optional[str] = None,
    municipio_nome: Optional[str] = None,
    municipio_uf: Optional[str] = None,
    ano: Optional[int] = None,
) -> None:
    """Salva (ou atualiza) o resultado de uma análise de paisagem para o Escritório Virtual do usuário."""
    lon, lat = point_lonlat if point_lonlat else (None, None)
    with get_db() as (db_type, conn, cursor):
        sql = _adapt_query(
            """
            INSERT INTO metric_results (
                user_email, fingerprint, label, data_source,
                point_lon, point_lat, buffer_dist,
                class_metrics_json, landscape_metrics_json, metric_names_json,
                created_at, municipio_codigo, municipio_nome, municipio_uf, ano
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_email, fingerprint) DO UPDATE SET
                label = EXCLUDED.label,
                data_source = EXCLUDED.data_source,
                point_lon = EXCLUDED.point_lon,
                point_lat = EXCLUDED.point_lat,
                buffer_dist = EXCLUDED.buffer_dist,
                class_metrics_json = EXCLUDED.class_metrics_json,
                landscape_metrics_json = EXCLUDED.landscape_metrics_json,
                metric_names_json = EXCLUDED.metric_names_json,
                created_at = EXCLUDED.created_at,
                municipio_codigo = EXCLUDED.municipio_codigo,
                municipio_nome = EXCLUDED.municipio_nome,
                municipio_uf = EXCLUDED.municipio_uf,
                ano = EXCLUDED.ano
            """,
            db_type,
        )
        params = (
            user_email,
            fingerprint,
            label,
            data_source,
            lon,
            lat,
            buffer_dist,
            class_metrics_df.to_json(orient="split"),
            json.dumps(landscape_metrics),
            json.dumps(list(class_metrics_df.columns)),
            datetime.now(timezone.utc).isoformat(),
            municipio_codigo,
            municipio_nome,
            municipio_uf,
            ano,
        )
        cursor.execute(sql, params)


def get_metric_result(
    user_email: str, fingerprint: str, required_metric_names: list
) -> Optional[dict]:
    """Retorna o resultado em cache para (user_email, fingerprint) no Escritório Virtual."""
    with get_db() as (db_type, conn, cursor):
        sql = _adapt_query(
            """
            SELECT class_metrics_json, landscape_metrics_json, metric_names_json
            FROM metric_results WHERE user_email = ? AND fingerprint = ?
            """,
            db_type,
        )
        cursor.execute(sql, (user_email, fingerprint))
        row = cursor.fetchone()

    if row is None:
        return None

    class_metrics_json, landscape_metrics_json, metric_names_json = row
    cached_metric_names = set(json.loads(metric_names_json))
    if not set(required_metric_names) <= cached_metric_names:
        return None

    return {
        "class_metrics_df_sub": pd.read_json(io.StringIO(class_metrics_json), orient="split"),
        "landscape_metrics": json.loads(landscape_metrics_json),
    }


def list_metric_results(user_email: str, full: bool = False) -> List[dict]:
    """Lista as análises do Escritório Virtual do usuário, mais recente primeiro."""
    columns = (
        "fingerprint, label, data_source, point_lon, point_lat, buffer_dist, created_at, "
        "municipio_codigo, municipio_nome, municipio_uf, ano"
    )
    if full:
        columns += ", class_metrics_json, landscape_metrics_json, metric_names_json"

    with get_db() as (db_type, conn, cursor):
        sql = _adapt_query(
            f"SELECT {columns} FROM metric_results WHERE user_email = ? ORDER BY created_at DESC",
            db_type,
        )
        cursor.execute(sql, (user_email,))
        rows = cursor.fetchall()

    col_names = [c.strip() for c in columns.split(",")]
    return [dict(zip(col_names, row)) for row in rows]


def delete_metric_result(user_email: str, fingerprint: str) -> None:
    """Remove uma análise salva no Escritório Virtual do usuário."""
    with get_db() as (db_type, conn, cursor):
        sql = _adapt_query(
            "DELETE FROM metric_results WHERE user_email = ? AND fingerprint = ?", db_type
        )
        cursor.execute(sql, (user_email, fingerprint))


def create_user(email: str, password: str) -> bool:
    """Cria um novo usuário na plataforma. Retorna False se o e-mail já existir."""
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    with get_db() as (db_type, conn, cursor):
        sql = _adapt_query(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)", db_type
        )
        try:
            # Em PostgreSQL/psycopg2, bytes usam a representação binária direta
            cursor.execute(
                sql, (email, bytes(password_hash), datetime.now(timezone.utc).isoformat())
            )
            return True
        except Exception as err:
            logger.warning(f"Erro ao criar usuário ({email}): {err}")
            return False


def verify_user(email: str, password: str) -> bool:
    """Valida o e-mail e senha informados contra o hash salvo no banco de dados."""
    with get_db() as (db_type, conn, cursor):
        sql = _adapt_query("SELECT password_hash FROM users WHERE email = ?", db_type)
        cursor.execute(sql, (email,))
        row = cursor.fetchone()

    if row is None or not row[0]:
        return False

    hash_val = row[0]
    if isinstance(hash_val, memoryview):
        hash_val = hash_val.tobytes()

    return bcrypt.checkpw(password.encode("utf-8"), hash_val)


def get_credentials(email: str) -> Optional[dict]:
    """Recupera e decifra as credenciais do GEE do usuário."""
    with get_db() as (db_type, conn, cursor):
        sql = _adapt_query("SELECT encrypted_json FROM user_credentials WHERE email = ?", db_type)
        cursor.execute(sql, (email,))
        row = cursor.fetchone()

    if row is None or not row[0]:
        return None

    enc_val = row[0]
    if isinstance(enc_val, memoryview):
        enc_val = enc_val.tobytes()

    fernet = _get_fernet()
    try:
        decrypted = fernet.decrypt(enc_val)
    except InvalidToken:
        logger.error(f"Falha ao decifrar credenciais para {email} (chave alterada ou dado corrompido)")
        return None

    return json.loads(decrypted.decode("utf-8"))


def save_credentials(email: str, credentials: dict) -> None:
    """Salva (ou atualiza) as credenciais criptografadas do GEE para o usuário."""
    fernet = _get_fernet()
    encrypted = fernet.encrypt(json.dumps(credentials).encode("utf-8"))
    with get_db() as (db_type, conn, cursor):
        sql = _adapt_query(
            """
            INSERT INTO user_credentials (email, encrypted_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                encrypted_json = EXCLUDED.encrypted_json,
                updated_at = EXCLUDED.updated_at
            """,
            db_type,
        )
        cursor.execute(
            sql, (email, bytes(encrypted), datetime.now(timezone.utc).isoformat())
        )


def get_user_settings(email: str) -> dict:
    """Recupera as configurações e preferências personalizadas do usuário."""
    with get_db() as (db_type, conn, cursor):
        sql = _adapt_query("SELECT settings_json FROM user_settings WHERE user_email = ?", db_type)
        cursor.execute(sql, (email,))
        row = cursor.fetchone()

    if row is None or not row[0]:
        return {
            "default_buffer_dist": 5000,
            "default_data_source": "mapbiomas",
            "default_uf": "GO",
            "selected_metrics": ["proportion_of_landscape", "number_of_patches", "edge_density", "shannon_diversity_index"],
        }

    return json.loads(row[0])


def save_user_settings(email: str, settings_dict: dict) -> None:
    """Salva (ou atualiza) as configurações individualizadas do usuário."""
    with get_db() as (db_type, conn, cursor):
        sql = _adapt_query(
            """
            INSERT INTO user_settings (user_email, settings_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_email) DO UPDATE SET
                settings_json = EXCLUDED.settings_json,
                updated_at = EXCLUDED.updated_at
            """,
            db_type,
        )
        cursor.execute(
            sql, (email, json.dumps(settings_dict), datetime.now(timezone.utc).isoformat())
        )

