"""
Rota para a Matriz Socioecológica (SSE) e Agrupamento Multivariado (K-Means e DBSCAN)
"""
import importlib
import io
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

import pandas as pd

from app.api.deps import get_current_user
from app.db import metric_results as metric_results_db


def _load_legacy_module(module_name: str):
    # backend/app/api/routes/sse.py -> parents[4] é a raiz do repo (uma
    # camada mais fundo que backend/app/services/landscape.py, que usa
    # parents[3] pelo mesmo motivo). Só "funcionava" antes por acidente: como
    # metrics.py roda primeiro em main.py e insere o caminho certo, o
    # root_dir errado calculado aqui nunca chegava a ser de fato necessário.
    root_dir = Path(__file__).resolve().parents[4]
    if str(root_dir) not in sys.path:
        sys.path.insert(0, str(root_dir))
    return importlib.import_module(module_name)


clustering = _load_legacy_module("clustering")


def _build_sse_matrix(user_email: str) -> pd.DataFrame:
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
        row.update({col: float(class_metrics[col].iloc[0]) if col in class_metrics.columns else 0.0 for col in class_metrics.columns})
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
    return pd.DataFrame(rows)

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
