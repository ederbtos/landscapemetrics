"""
Descrição da funcionalidade
---------------------------
Estações e séries históricas hidroclimáticas da ANA (vazão, nível, chuva),
via HidroWebService (https://www.ana.gov.br/hidrowebservice). O schema já
fica pronto, mas a ingestão real (`scripts/seed_ana_hidroclimatica.py`) fica
bloqueada até existir uma credencial de API da ANA — pedida manualmente por
e-mail a hidro@ana.gov.br (assunto "Solicitação de acesso à API"), não é
algo que se resolve por código. Ver docstring do script de seed.
"""
import sqlite3
from contextlib import closing

from app.core.config import get_settings


def init_ana_hidroclimatica_tables() -> None:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ana_estacoes (
                codigo TEXT PRIMARY KEY,
                nome TEXT,
                lat REAL,
                lon REAL,
                uf TEXT,
                municipio_codigo TEXT,
                tipo TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ana_serie_historica (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                estacao_codigo TEXT NOT NULL,
                data TEXT NOT NULL,
                vazao_m3s REAL,
                nivel_cm REAL,
                chuva_mm REAL,
                consistencia TEXT,
                UNIQUE(estacao_codigo, data)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ana_serie_estacao ON ana_serie_historica(estacao_codigo)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ana_estacoes_municipio ON ana_estacoes(municipio_codigo)"
        )
        conn.commit()


def save_estacao(
    codigo: str, nome: str | None, lat: float | None, lon: float | None,
    uf: str | None, municipio_codigo: str | None, tipo: str | None,
) -> None:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        conn.execute(
            """
            INSERT INTO ana_estacoes (codigo, nome, lat, lon, uf, municipio_codigo, tipo)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(codigo) DO UPDATE SET
                nome = excluded.nome,
                lat = excluded.lat,
                lon = excluded.lon,
                uf = excluded.uf,
                municipio_codigo = excluded.municipio_codigo,
                tipo = excluded.tipo
            """,
            (codigo, nome, lat, lon, uf, municipio_codigo, tipo),
        )
        conn.commit()


def save_serie_ponto(
    estacao_codigo: str, data: str, vazao_m3s: float | None,
    nivel_cm: float | None, chuva_mm: float | None, consistencia: str | None,
) -> None:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        conn.execute(
            """
            INSERT INTO ana_serie_historica
                (estacao_codigo, data, vazao_m3s, nivel_cm, chuva_mm, consistencia)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(estacao_codigo, data) DO UPDATE SET
                vazao_m3s = excluded.vazao_m3s,
                nivel_cm = excluded.nivel_cm,
                chuva_mm = excluded.chuva_mm,
                consistencia = excluded.consistencia
            """,
            (estacao_codigo, data, vazao_m3s, nivel_cm, chuva_mm, consistencia),
        )
        conn.commit()


def list_estacoes_by_municipio(municipio_codigo: str) -> list:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        rows = conn.execute(
            "SELECT codigo, nome, lat, lon, tipo FROM ana_estacoes WHERE municipio_codigo = ?",
            (municipio_codigo,),
        ).fetchall()
    cols = ["codigo", "nome", "lat", "lon", "tipo"]
    return [dict(zip(cols, row)) for row in rows]


def get_serie_estacao(codigo: str) -> list:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        rows = conn.execute(
            """
            SELECT data, vazao_m3s, nivel_cm, chuva_mm, consistencia
            FROM ana_serie_historica WHERE estacao_codigo = ? ORDER BY data
            """,
            (codigo,),
        ).fetchall()
    cols = ["data", "vazao_m3s", "nivel_cm", "chuva_mm", "consistencia"]
    return [dict(zip(cols, row)) for row in rows]
