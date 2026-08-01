"""
Descrição da funcionalidade
---------------------------
Atlas Nacional de Paisagem — Fase 0 (Diversidade): índices de diversidade e
composição por município/ano, pré-computados a partir de
`mapbiomas_municipio_stats` (ver `app.services.diversity_atlas` para o
cálculo puro e `scripts/build_diversity_atlas.py` para o job que popula esta
tabela). Pré-computado (não calculado a cada request) porque um ranking
nacional precisa varrer ~5.570 municípios rapidamente, contra uma
`mapbiomas_municipio_stats` com mais de 1 milhão de linhas
(classe x ano x município).

Diferente de toda outra tabela de referência do app, as rotas que leem daqui
(`api/routes/atlas.py`) são deliberadamente PÚBLICAS (sem
`Depends(get_current_user)`) — é a vitrine nacional do Atlas.
"""
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from app.core.config import get_settings

# Whitelist de colunas ordenáveis via API (evita interpolar `metrica` cru
# num ORDER BY — a rota é pública, sem autenticação, então isso é a única
# barreira contra injeção de SQL via esse parâmetro).
RANKING_METRIC_COLUMNS = {
    "shannon_diversity_index", "shannon_evenness_index",
    "simpson_diversity_index", "simpson_evenness_index",
    "patch_richness", "area_natural_pct", "area_antropizada_pct",
    "area_nao_vegetada_pct", "area_agua_pct", "classe_dominante_pct",
    "area_total_ha",
}

_METRICS_ROW = (
    "area_total_ha", "classe_dominante_codigo", "classe_dominante_nome",
    "classe_dominante_pct", "area_natural_pct", "area_antropizada_pct",
    "area_nao_vegetada_pct", "area_agua_pct", "patch_richness",
    "shannon_diversity_index", "shannon_evenness_index",
    "simpson_diversity_index", "simpson_evenness_index",
)


def init_diversity_atlas_table() -> None:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS diversity_atlas_municipio (
                municipio_codigo TEXT NOT NULL,
                ano INTEGER NOT NULL,
                {", ".join(f"{col} REAL" for col in _METRICS_ROW if col not in ("classe_dominante_codigo", "classe_dominante_nome"))},
                classe_dominante_codigo INTEGER,
                classe_dominante_nome TEXT,
                atualizado_em TEXT NOT NULL,
                PRIMARY KEY (municipio_codigo, ano)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_diversity_atlas_ano ON diversity_atlas_municipio(ano)"
        )
        conn.commit()


def upsert_diversity_atlas_row(municipio_codigo: str, ano: int, metrics: dict) -> None:
    columns = ["municipio_codigo", "ano", *_METRICS_ROW, "atualizado_em"]
    values = [
        municipio_codigo, ano,
        *[metrics.get(col) for col in _METRICS_ROW],
        datetime.now(timezone.utc).isoformat(),
    ]
    placeholders = ", ".join("?" for _ in columns)
    update_clause = ", ".join(f"{col} = excluded.{col}" for col in (*_METRICS_ROW, "atualizado_em"))
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        conn.execute(
            f"""
            INSERT INTO diversity_atlas_municipio ({", ".join(columns)})
            VALUES ({placeholders})
            ON CONFLICT(municipio_codigo, ano) DO UPDATE SET {update_clause}
            """,
            values,
        )
        conn.commit()


def get_anos_disponiveis() -> list:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        rows = conn.execute(
            "SELECT DISTINCT ano FROM diversity_atlas_municipio ORDER BY ano"
        ).fetchall()
    return [r[0] for r in rows]


def get_ranking(ano: int, metrica: str, ordem: str = "desc", uf: str | None = None,
                 limit: int = 100, offset: int = 0) -> list:
    if metrica not in RANKING_METRIC_COLUMNS:
        raise ValueError(f"Métrica de ranking inválida: {metrica!r}")
    ordem_sql = "DESC" if ordem.lower() != "asc" else "ASC"

    query = f"""
        SELECT d.municipio_codigo, m.nome AS municipio_nome, m.uf AS municipio_uf,
               d.{metrica} AS valor, {", ".join(f"d.{col}" for col in _METRICS_ROW)}
        FROM diversity_atlas_municipio d
        JOIN municipios_malha m ON m.codigo_ibge = d.municipio_codigo
        WHERE d.ano = ? AND d.{metrica} IS NOT NULL
        {"AND m.uf = ?" if uf else ""}
        ORDER BY d.{metrica} {ordem_sql}
        LIMIT ? OFFSET ?
    """
    params: list = [ano]
    if uf:
        params.append(uf.upper())
    params.extend([limit, offset])

    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        cols = [desc[0] for desc in conn.execute(query, params).description]
        rows = conn.execute(query, params).fetchall()
    return [dict(zip(cols, row)) for row in rows]


def get_municipio_series(municipio_codigo: str) -> list:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        query = f"""
            SELECT ano, {", ".join(_METRICS_ROW)}
            FROM diversity_atlas_municipio
            WHERE municipio_codigo = ?
            ORDER BY ano
        """
        cols = [desc[0] for desc in conn.execute(query, (municipio_codigo,)).description]
        rows = conn.execute(query, (municipio_codigo,)).fetchall()
    return [dict(zip(cols, row)) for row in rows]


def get_ranking_trend(ano_inicio: int, ano_fim: int, uf: str | None = None, limit: int = 100) -> list:
    """Municípios com maior VARIAÇÃO de área natural entre dois anos
    (self-join de `diversity_atlas_municipio` contra si mesma) — ordenado do
    maior perda para o maior ganho (mais perda de vegetação nativa primeiro),
    o indicador mais "disruptivo" do Atlas."""
    query = f"""
        SELECT
            d_fim.municipio_codigo, m.nome AS municipio_nome, m.uf AS municipio_uf,
            d_inicio.area_natural_pct AS area_natural_pct_inicio,
            d_fim.area_natural_pct AS area_natural_pct_fim,
            (d_fim.area_natural_pct - d_inicio.area_natural_pct) AS variacao_area_natural_pp
        FROM diversity_atlas_municipio d_fim
        JOIN diversity_atlas_municipio d_inicio
            ON d_inicio.municipio_codigo = d_fim.municipio_codigo AND d_inicio.ano = ?
        JOIN municipios_malha m ON m.codigo_ibge = d_fim.municipio_codigo
        WHERE d_fim.ano = ?
        {"AND m.uf = ?" if uf else ""}
        ORDER BY variacao_area_natural_pp ASC
        LIMIT ?
    """
    params: list = [ano_inicio, ano_fim]
    if uf:
        params.append(uf.upper())
    params.append(limit)

    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        cols = [desc[0] for desc in conn.execute(query, params).description]
        rows = conn.execute(query, params).fetchall()
    return [dict(zip(cols, row)) for row in rows]


def get_mapa_geojson(ano: int, metrica: str, uf: str | None = None) -> dict:
    if metrica not in RANKING_METRIC_COLUMNS:
        raise ValueError(f"Métrica de mapa inválida: {metrica!r}")

    query = f"""
        SELECT m.codigo_ibge, m.nome, m.uf, m.geojson, d.{metrica} AS valor
        FROM diversity_atlas_municipio d
        JOIN municipios_malha m ON m.codigo_ibge = d.municipio_codigo
        WHERE d.ano = ? AND d.{metrica} IS NOT NULL
        {"AND m.uf = ?" if uf else ""}
    """
    params: list = [ano]
    if uf:
        params.append(uf.upper())

    import json

    features = []
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        rows = conn.execute(query, params).fetchall()

    for codigo_ibge, nome, municipio_uf, geojson_str, valor in rows:
        try:
            geom = json.loads(geojson_str)["features"][0]["geometry"]
        except (KeyError, IndexError, ValueError):
            continue
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "codigo_ibge": codigo_ibge, "nome": nome, "uf": municipio_uf,
                "metrica": metrica, "valor": valor,
            },
        })

    return {"type": "FeatureCollection", "features": features}
