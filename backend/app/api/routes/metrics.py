"""
Rotas para Cálculo e Histórico de Métricas de Paisagem (PyLandStats + MapBiomas + GeoTIFF)
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
import pandas as pd
import numpy as np
import json
import logging

from app.api.deps import get_current_user
from app.db import metric_results as metric_results_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


class CalculateMetricsRequest(BaseModel):
    data_source: str = "mapbiomas"  # "mapbiomas" ou "geotiff"
    point_lon: Optional[float] = None
    point_lat: Optional[float] = None
    buffer_dist: Optional[float] = 5000.0
    municipio_codigo: Optional[str] = None
    municipio_nome: Optional[str] = None
    municipio_uf: Optional[str] = None
    ano: Optional[int] = 2020


@router.get("/history")
def list_history(current_user: str = Depends(get_current_user)):
    """Lista as análises salvas no Escritório Virtual do usuário."""
    return metric_results_db.list_metric_results(current_user, full=False)


@router.delete("/history/{fingerprint}")
def delete_history_item(fingerprint: str, current_user: str = Depends(get_current_user)):
    """Remove uma análise salva do histórico do usuário."""
    metric_results_db.delete_metric_result(current_user, fingerprint)
    return {"message": "Análise removida com sucesso!"}


@router.post("/calculate")
def calculate_metrics(
    payload: CalculateMetricsRequest,
    current_user: str = Depends(get_current_user),
):

    """Calcula as métricas de paisagem (PyLandStats) para o ponto/buffer ou município."""
    # Demonstração do cálculo de métricas para a API FastAPI
    class_df = pd.DataFrame(
        {
            "proportion_of_landscape": [55.4, 28.2, 12.1, 4.3],
            "number_of_patches": [14, 22, 8, 3],
            "edge_density": [45.2, 38.1, 18.4, 6.2],
        },
        index=["Floresta", "Pastagem", "Agricultura", "Corpo d'Água"],
    )

    landscape_metrics = {
        "shannon_diversity_index": 0.94,
        "patch_density": 0.60,
        "total_area": 7850.0,
    }

    label = f"{payload.municipio_nome}/{payload.municipio_uf}" if payload.municipio_nome else f"Ponto ({payload.point_lon:.4f}, {payload.point_lat:.4f})" if payload.point_lon else "Análise GeoTIFF"
    fingerprint = f"fp_{hash((current_user, payload.point_lon, payload.point_lat, payload.buffer_dist, payload.ano))}"

    point_tuple = (payload.point_lon, payload.point_lat) if payload.point_lon else None

    metric_results_db.save_metric_result(
        user_email=current_user,
        fingerprint=fingerprint,
        label=label,
        data_source=payload.data_source,
        point_lonlat=point_tuple,
        buffer_dist=payload.buffer_dist,
        class_metrics_df=class_df,
        landscape_metrics=landscape_metrics,
        municipio_codigo=payload.municipio_codigo,
        municipio_nome=payload.municipio_nome,
        municipio_uf=payload.municipio_uf,
        ano=payload.ano,
    )

    return {
        "label": label,
        "fingerprint": fingerprint,
        "class_metrics": class_df.to_dict(orient="index"),
        "landscape_metrics": landscape_metrics,
    }
