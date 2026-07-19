"""
Descrição da funcionalidade
---------------------------
Cache/histórico de métricas já calculadas (`metric_results`) — porte de
`db.py::save_metric_result/get_metric_result/list_metric_results/
delete_metric_result`, mesmo schema/semântica (chave `(user_email,
fingerprint)`, cache miss se faltar alguma métrica exigida — ver docstring
original em db.py). Usado por `services/metrics.py`/`services/sse_matrix.py`
na Fase 2.
"""
import io
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

import pandas as pd

from app.core.config import get_settings


def save_metric_result(
    user_email: str,
    fingerprint: str,
    label: str,
    data_source: str,
    point_lonlat: tuple | None,
    buffer_dist: float | None,
    class_metrics_df,
    landscape_metrics: dict,
    municipio_codigo: str | None = None,
    municipio_nome: str | None = None,
    municipio_uf: str | None = None,
    ano: int | None = None,
) -> None:
    lon, lat = point_lonlat if point_lonlat else (None, None)
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        conn.execute(
            """
            INSERT INTO metric_results (
                user_email, fingerprint, label, data_source,
                point_lon, point_lat, buffer_dist,
                class_metrics_json, landscape_metrics_json, metric_names_json,
                created_at, municipio_codigo, municipio_nome, municipio_uf, ano
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_email, fingerprint) DO UPDATE SET
                label = excluded.label,
                data_source = excluded.data_source,
                point_lon = excluded.point_lon,
                point_lat = excluded.point_lat,
                buffer_dist = excluded.buffer_dist,
                class_metrics_json = excluded.class_metrics_json,
                landscape_metrics_json = excluded.landscape_metrics_json,
                metric_names_json = excluded.metric_names_json,
                created_at = excluded.created_at,
                municipio_codigo = excluded.municipio_codigo,
                municipio_nome = excluded.municipio_nome,
                municipio_uf = excluded.municipio_uf,
                ano = excluded.ano
            """,
            (
                user_email, fingerprint, label, data_source,
                lon, lat, buffer_dist,
                class_metrics_df.to_json(orient="split"),
                json.dumps(landscape_metrics),
                json.dumps(list(class_metrics_df.columns)),
                datetime.now(timezone.utc).isoformat(),
                municipio_codigo, municipio_nome, municipio_uf, ano,
            ),
        )
        conn.commit()


def get_metric_result(user_email: str, fingerprint: str, required_metric_names: list) -> dict | None:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        row = conn.execute(
            """
            SELECT class_metrics_json, landscape_metrics_json, metric_names_json
            FROM metric_results WHERE user_email = ? AND fingerprint = ?
            """,
            (user_email, fingerprint),
        ).fetchone()
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


def list_metric_results(user_email: str, full: bool = False) -> list:
    columns = (
        "fingerprint, label, data_source, point_lon, point_lat, buffer_dist, created_at, "
        "municipio_codigo, municipio_nome, municipio_uf, ano"
    )
    if full:
        columns += ", class_metrics_json, landscape_metrics_json, metric_names_json"
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        rows = conn.execute(
            f"""
            SELECT {columns} FROM metric_results
            WHERE user_email = ? ORDER BY created_at DESC
            """,
            (user_email,),
        ).fetchall()
    col_names = [c.strip() for c in columns.split(",")]
    return [dict(zip(col_names, row)) for row in rows]


def delete_metric_result(user_email: str, fingerprint: str) -> None:
    with closing(sqlite3.connect(get_settings().db_path)) as conn:
        conn.execute(
            "DELETE FROM metric_results WHERE user_email = ? AND fingerprint = ?",
            (user_email, fingerprint),
        )
        conn.commit()
