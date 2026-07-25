"""
Rota de Aprendizado Supervisionado (Random Forest, XGBoost e LightGBM com Validação Espacial)
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
import pandas as pd

import importlib
import sys
from pathlib import Path

from app.api.deps import get_current_user
from app.db import metric_results as metric_results_db


def _load_legacy_module(module_name: str):
    root_dir = Path(__file__).resolve().parents[3]
    if str(root_dir) not in sys.path:
        sys.path.insert(0, str(root_dir))
    return importlib.import_module(module_name)


supervised_models = _load_legacy_module("supervised_models")

router = APIRouter(prefix="/api/supervised", tags=["supervised"])


class SupervisedTrainRequest(BaseModel):
    feature_cols: List[str]
    target_col: str
    model_name: str = "random_forest"  # "random_forest", "xgboost", ou "lightgbm"
    n_splits: int = 5


@router.post("/train")
def train_supervised(
    req: SupervisedTrainRequest, current_user: str = Depends(get_current_user)
):
    """Treina um modelo supervisionado (Random Forest, XGBoost ou LightGBM) com Validação Cruzada Espacial (Spatial K-Fold)."""
    df = _build_sse_matrix(current_user)
    if df.empty or len(df) < 4:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="É necessário ter pelo menos 4 análises salvas para executar o treinamento supervisionado com validação cruzada espacial.",
        )

    res = supervised_models.train_supervised_model(
        df,
        req.feature_cols,
        req.target_col,
        model_name=req.model_name,
        n_splits=req.n_splits,
    )

    if "error" in res:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=res["error"])

    return res
