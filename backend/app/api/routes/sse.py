"""
Rota para a Matriz Socioecológica (SSE) e Agrupamento Multivariado (K-Means e DBSCAN)
"""
import io
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

import pandas as pd

from app.api.deps import get_current_user
from app.db import metric_results as metric_results_db
from app.services import clustering


def _build_sse_matrix(user_email: str) -> pd.DataFrame:
    """Monta a base da matriz socioecológica (SSE): uma linha por análise já
    salva do usuário, colunas = proporção de área por classe de cobertura do
    solo (wide, `pct_{classe}`) + métricas de nível de paisagem
    (`landscape_{nome}`) + identificação. Só usa o que já está persistido —
    não recalcula nada.

    Regressão corrigida: a versão anterior iterava `class_metrics.columns`
    (nomes de MÉTRICA, ex. "total_area"/"proportion_of_landscape") e pegava
    só `.iloc[0]` (a primeira linha) — para qualquer análise com mais de uma
    classe presente (o caso normal), isso descartava silenciosamente todas
    as classes menos a primeira, sem gerar coluna nenhuma por classe. O
    correto é pivotar a coluna `proportion_of_landscape` (cujo índice são os
    nomes de classe) em uma coluna `pct_{classe}` por linha — mesma lógica
    de antes da migração para o backend (app.py, removido)."""
    history = metric_results_db.list_metric_results(user_email, full=True)
    if not history:
        return pd.DataFrame()

    rows = []
    for item in history:
        try:
            class_metrics = pd.read_json(io.StringIO(item["class_metrics_json"]), orient="split")
        except Exception:
            continue
        landscape_metrics = json.loads(item.get("landscape_metrics_json", "{}")) if item.get("landscape_metrics_json") else {}
        row = {"label": item.get("label"), "data_source": item.get("data_source")}
        if "proportion_of_landscape" in class_metrics.columns:
            for cls_name, value in class_metrics["proportion_of_landscape"].items():
                row[f"pct_{cls_name}"] = value
        if isinstance(landscape_metrics, dict):
            row.update({f"landscape_{k}": v for k, v in landscape_metrics.items()})
        row.update({
            "point_lon": item.get("point_lon"),
            "point_lat": item.get("point_lat"),
            "buffer_dist": item.get("buffer_dist"),
            "municipio_codigo": item.get("municipio_codigo"),
            "municipio_nome": item.get("municipio_nome"),
            "municipio_uf": item.get("municipio_uf"),
            "ano": item.get("ano"),
        })
        rows.append(row)

    matrix = pd.DataFrame(rows)
    # Colunas pct_* ausentes numa linha significam "classe não presente
    # nessa análise" (0%), não um dado faltante — só essas colunas levam
    # fillna(0); o resto (município, ano, métricas de paisagem) fica NaN de
    # propósito quando ausente.
    pct_cols = [c for c in matrix.columns if c.startswith("pct_")]
    if pct_cols:
        matrix[pct_cols] = matrix[pct_cols].fillna(0.0)
    return matrix

router = APIRouter(prefix="/api/sse", tags=["sse"])


class KMeansRequest(BaseModel):
    feature_cols: List[str]
    k: int = 3
    show_elbow: bool = True


class DBSCANRequest(BaseModel):
    feature_cols: List[str]
    eps: float = 0.8
    min_samples: int = 2


@router.get("/matrix")
def get_sse_matrix(current_user: str = Depends(get_current_user)):
    """Retorna a Matriz Socioecológica agregada do usuário."""
    df = _build_sse_matrix(current_user)

    if df.empty:
        return {"records": [], "columns": [], "numeric_columns": []}

    records = df.to_dict(orient="records")
    columns = list(df.columns)
    import numpy as np
    numeric_columns = df.select_dtypes(include=[np.number]).columns.tolist()

    return {
        "records": records,
        "columns": columns,
        "numeric_columns": numeric_columns,
    }


@router.post("/cluster/kmeans")
def run_kmeans_clustering(
    req: KMeansRequest, current_user: str = Depends(get_current_user)
):

    df = _build_sse_matrix(current_user)
    if df.empty or len(df) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="É necessário ter pelo menos 2 análises salvas para executar o K-Means.",
        )

    res = clustering.run_kmeans(df, req.feature_cols, k=req.k)
    elbow_df = pd.DataFrame()
    if req.show_elbow:
        elbow_df = clustering.compute_elbow_curve(df, req.feature_cols, max_k=min(10, len(df)))

    import pandas as pd
    return {
        "k": res["k"],
        "silhouette": res["silhouette"],
        "inertia": res["inertia"],
        "pca_data": res["pca_df"].to_dict(orient="records") if not res["pca_df"].empty else [],
        "cluster_profiles": res["cluster_profiles"].to_dict(orient="index") if not res["cluster_profiles"].empty else {},
        "elbow_curve": elbow_df.to_dict(orient="records") if not elbow_df.empty else [],
    }


@router.post("/cluster/dbscan")
def run_dbscan_clustering(
    req: DBSCANRequest, current_user: str = Depends(get_current_user)
):

    df = _build_sse_matrix(current_user)
    if df.empty or len(df) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="É necessário ter pelo menos 2 análises salvas para executar o DBSCAN.",
        )

    res = clustering.run_dbscan(df, req.feature_cols, eps=req.eps, min_samples=req.min_samples)

    return {
        "n_clusters": res["n_clusters"],
        "n_noise": res["n_noise"],
        "pca_data": res["pca_df"].to_dict(orient="records") if not res["pca_df"].empty else [],
        "cluster_profiles": res["cluster_profiles"].to_dict(orient="index") if not res["cluster_profiles"].empty else {},
    }
