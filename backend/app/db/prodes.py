"""
Descrição da funcionalidade
---------------------------
Registros de desmatamento do PRODES/INPE, em todos os biomas monitorados,
obtidos via WFS do GeoServer do TerraBrasilis
(https://terrabrasilis.dpi.inpe.br/geoserver/ows). Populada por
`scripts/seed_prodes.py`. `municipio_codigo` é preenchido por junção
espacial (centroide da feature dentro do polígono do município, via
shapely) contra `municipios_malha` — segue a regra de "nunca fabricar dado"
do resto do projeto: se a junção não encontrar um município, o campo fica
`NULL` em vez de um palpite.
"""
import sqlite3
from contextlib import closing

from app.core.config import get_settings


def init_prodes_table() -> None:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS prodes_desmatamento (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bioma TEXT NOT NULL,
                feature_id TEXT NOT NULL,
                municipio_codigo TEXT,
                ano_deteccao INTEGER,
                area_km2 REAL,
                geojson TEXT,
                UNIQUE(bioma, feature_id)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_prodes_municipio_ano
            ON prodes_desmatamento(municipio_codigo, ano_deteccao)
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_prodes_bioma ON prodes_desmatamento(bioma)"
        )
        conn.commit()


def save_prodes_feature(
    bioma: str,
    feature_id: str,
    municipio_codigo: str | None,
    ano_deteccao: int | None,
    area_km2: float | None,
    geojson_str: str | None,
) -> None:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        conn.execute(
            """
            INSERT INTO prodes_desmatamento
                (bioma, feature_id, municipio_codigo, ano_deteccao, area_km2, geojson)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(bioma, feature_id) DO UPDATE SET
                municipio_codigo = excluded.municipio_codigo,
                ano_deteccao = excluded.ano_deteccao,
                area_km2 = excluded.area_km2,
                geojson = excluded.geojson
            """,
            (bioma, feature_id, municipio_codigo, ano_deteccao, area_km2, geojson_str),
        )
        conn.commit()


def list_prodes_by_municipio(municipio_codigo: str) -> list:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        rows = conn.execute(
            """
            SELECT bioma, ano_deteccao, area_km2
            FROM prodes_desmatamento
            WHERE municipio_codigo = ?
            ORDER BY ano_deteccao
            """,
            (municipio_codigo,),
        ).fetchall()
    cols = ["bioma", "ano_deteccao", "area_km2"]
    return [dict(zip(cols, row)) for row in rows]


def count_by_bioma() -> dict:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        rows = conn.execute(
            "SELECT bioma, COUNT(*) FROM prodes_desmatamento GROUP BY bioma"
        ).fetchall()
    return dict(rows)
