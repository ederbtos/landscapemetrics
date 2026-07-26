"""
Descrição da funcionalidade
---------------------------
Cache nacional da malha municipal do IBGE (~5.570 municípios) — elimina a
dependência de chamada em tempo real à API do IBGE por município, usada
hoje em `api/routes/ibge.py`/`landscape_core.py::_ibge_get_municipio_geojson`.
Populada por `scripts/seed_municipios_malha.py`. Geometria guardada como
GeoJSON em TEXT — mesmo padrão de `class_metrics_json` em `metric_results`
(sem PostGIS neste projeto, ver `backend/app/db/schema.py`).
"""
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from app.core.config import get_settings


def init_municipios_table() -> None:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS municipios_malha (
                codigo_ibge TEXT PRIMARY KEY,
                nome TEXT NOT NULL,
                uf TEXT NOT NULL,
                geojson TEXT NOT NULL,
                populacao_estimada INTEGER,
                atualizado_em TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_municipios_malha_uf ON municipios_malha(uf)"
        )
        conn.commit()


def save_municipio_malha(
    codigo_ibge: str,
    nome: str,
    uf: str,
    geojson_str: str,
    populacao_estimada: int | None = None,
) -> None:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        conn.execute(
            """
            INSERT INTO municipios_malha
                (codigo_ibge, nome, uf, geojson, populacao_estimada, atualizado_em)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(codigo_ibge) DO UPDATE SET
                nome = excluded.nome,
                uf = excluded.uf,
                geojson = excluded.geojson,
                populacao_estimada = excluded.populacao_estimada,
                atualizado_em = excluded.atualizado_em
            """,
            (
                codigo_ibge, nome, uf, geojson_str, populacao_estimada,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def get_municipio_malha(codigo_ibge: str) -> dict | None:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        row = conn.execute(
            """
            SELECT codigo_ibge, nome, uf, geojson, populacao_estimada, atualizado_em
            FROM municipios_malha WHERE codigo_ibge = ?
            """,
            (codigo_ibge,),
        ).fetchone()
    if row is None:
        return None
    cols = ["codigo_ibge", "nome", "uf", "geojson", "populacao_estimada", "atualizado_em"]
    return dict(zip(cols, row))


def list_municipios_by_uf(uf: str) -> list:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        rows = conn.execute(
            """
            SELECT codigo_ibge, nome, uf, populacao_estimada
            FROM municipios_malha WHERE uf = ? ORDER BY nome
            """,
            (uf.upper(),),
        ).fetchall()
    cols = ["codigo_ibge", "nome", "uf", "populacao_estimada"]
    return [dict(zip(cols, row)) for row in rows]


def count_municipios() -> int:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        return conn.execute("SELECT COUNT(*) FROM municipios_malha").fetchone()[0]


def all_municipio_codes() -> list:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        rows = conn.execute("SELECT codigo_ibge FROM municipios_malha").fetchall()
    return [r[0] for r in rows]
