"""
Descrição da funcionalidade
---------------------------
Estatísticas de uso e cobertura da terra do MapBiomas agregadas por
município/ano/classe (área em hectares) — não pixels (guardar raster
nacional de 20 anos seria da ordem de dezenas de TB, inviável). Populada por
`scripts/seed_mapbiomas_stats.py`, via `ee.Image.reduceRegions` contra a
malha municipal (`municipios_malha`) ou via importação do Excel oficial de
Estatísticas do MapBiomas (`--from-excel`) — a coluna `fonte` documenta qual
dos dois caminhos gerou cada linha.
"""
import sqlite3
from contextlib import closing

from app.core.config import get_settings


def init_mapbiomas_stats_table() -> None:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mapbiomas_municipio_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                municipio_codigo TEXT NOT NULL,
                ano INTEGER NOT NULL,
                classe_codigo INTEGER NOT NULL,
                classe_nome TEXT,
                area_ha REAL NOT NULL,
                fonte TEXT NOT NULL,
                UNIQUE(municipio_codigo, ano, classe_codigo)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_mapbiomas_stats_municipio_ano
            ON mapbiomas_municipio_stats(municipio_codigo, ano)
            """
        )
        conn.commit()


def save_mapbiomas_stat(
    municipio_codigo: str,
    ano: int,
    classe_codigo: int,
    classe_nome: str | None,
    area_ha: float,
    fonte: str,
) -> None:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        conn.execute(
            """
            INSERT INTO mapbiomas_municipio_stats
                (municipio_codigo, ano, classe_codigo, classe_nome, area_ha, fonte)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(municipio_codigo, ano, classe_codigo) DO UPDATE SET
                classe_nome = excluded.classe_nome,
                area_ha = excluded.area_ha,
                fonte = excluded.fonte
            """,
            (municipio_codigo, ano, classe_codigo, classe_nome, area_ha, fonte),
        )
        conn.commit()


def get_serie_municipio(municipio_codigo: str) -> list:
    """Série completa (todos os anos/classes já carregados) de um município —
    usada pela rota `/api/mapbiomas/serie/{codigo}` e, futuramente, para
    alimentar a predição de Markov com histórico real (hoje só via upload de
    múltiplos GeoTIFFs)."""
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        rows = conn.execute(
            """
            SELECT ano, classe_codigo, classe_nome, area_ha
            FROM mapbiomas_municipio_stats
            WHERE municipio_codigo = ?
            ORDER BY ano, classe_codigo
            """,
            (municipio_codigo,),
        ).fetchall()
    cols = ["ano", "classe_codigo", "classe_nome", "area_ha"]
    return [dict(zip(cols, row)) for row in rows]


def anos_disponiveis(municipio_codigo: str) -> list:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT ano FROM mapbiomas_municipio_stats
            WHERE municipio_codigo = ? ORDER BY ano
            """,
            (municipio_codigo,),
        ).fetchall()
    return [r[0] for r in rows]
