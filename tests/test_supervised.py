"""
Testes unitários para o módulo de Aprendizado Supervisionado (supervised_models.py)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.supervised_models import (
    get_spatial_groups,
    prepare_supervised_data,
    train_supervised_model,
)


@pytest.fixture
def sample_spatial_df():
    """Gera um DataFrame sintético com atributos de paisagem, espacialidade e alvo binário."""
    np.random.seed(42)
    n = 30
    return pd.DataFrame({
        "point_lat": np.random.uniform(-15.0, -10.0, n),
        "point_lon": np.random.uniform(-50.0, -45.0, n),
        "municipio_codigo": [f"52000{i % 5}" for i in range(n)],
        "pct_Floresta": np.random.uniform(10.0, 80.0, n),
        "pct_Pastagem": np.random.uniform(5.0, 60.0, n),
        "SHDI": np.random.uniform(0.2, 1.2, n),
        "edge_density": np.random.uniform(5.0, 50.0, n),
        "target_class": np.random.choice(["Alta Fragmentacao", "Baixa Fragmentacao"], n),
    })


def test_prepare_supervised_data(sample_spatial_df):
    feature_cols = ["pct_Floresta", "pct_Pastagem", "SHDI"]
    X_scaled, y, valid_cols, scaler, clean_df = prepare_supervised_data(
        sample_spatial_df, feature_cols, "target_class"
    )

    assert X_scaled.shape[0] == 30
    assert X_scaled.shape[1] == 3
    assert len(y) == 30
    assert set(np.unique(y)) == {0, 1}
    assert valid_cols == feature_cols


def test_get_spatial_groups(sample_spatial_df):
    groups = get_spatial_groups(sample_spatial_df, n_splits=5)
    assert len(groups) == 30
    assert len(np.unique(groups)) == 5


def test_get_spatial_groups_falls_back_to_municipio_when_points_are_null():
    """Regressão: análises só por município (sem ponto+buffer) têm as
    colunas point_lat/point_lon presentes na matriz SSE, mas totalmente
    nulas — get_spatial_groups checava só a presença da coluna, preenchia
    com fillna(0.0) e mandava tudo pro KMeans, que degenerava num único
    cluster (todos os pontos em (0,0)) e quebrava o GroupKFold seguinte com
    "n_splits maior que o número de grupos" para qualquer usuário nessa
    situação (ex.: só análises via lote por município)."""
    df = pd.DataFrame({
        "point_lat": [None, None, None, None],
        "point_lon": [None, None, None, None],
        "municipio_codigo": ["5200050", "5200050", "5200100", "5200100"],
    })

    groups = get_spatial_groups(df, n_splits=2)

    assert len(groups) == 4
    assert len(np.unique(groups)) == 2


def test_train_random_forest(sample_spatial_df):
    feature_cols = ["pct_Floresta", "pct_Pastagem", "SHDI", "edge_density"]
    res = train_supervised_model(
        sample_spatial_df, feature_cols, "target_class", model_name="random_forest", n_splits=3
    )

    assert res["model_name"] == "random_forest"
    assert res["f1_score"] >= 0.0
    assert len(res["confusion_matrix"]) == 2
    assert "pct_Floresta" in res["permutation_importance"]
    assert res["n_splits"] == 3


def test_train_xgboost(sample_spatial_df):
    feature_cols = ["pct_Floresta", "pct_Pastagem", "SHDI"]
    res = train_supervised_model(
        sample_spatial_df, feature_cols, "target_class", model_name="xgboost", n_splits=3
    )

    assert res["model_name"] == "xgboost"
    assert res["f1_score"] >= 0.0
    assert len(res["confusion_matrix"]) == 2
    assert "pct_Floresta" in res["permutation_importance"]


def test_train_lightgbm(sample_spatial_df):
    feature_cols = ["pct_Floresta", "pct_Pastagem", "SHDI"]
    res = train_supervised_model(
        sample_spatial_df, feature_cols, "target_class", model_name="lightgbm", n_splits=3
    )

    assert res["model_name"] == "lightgbm"
    assert res["f1_score"] >= 0.0
    assert len(res["confusion_matrix"]) == 2
    assert "pct_Floresta" in res["permutation_importance"]
