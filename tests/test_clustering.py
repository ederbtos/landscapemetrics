"""
Testes unitários para o módulo clustering.py (K-Means, DBSCAN, PCA, Elbow Method)
"""
import numpy as np
import pandas as pd
import pytest

import clustering


@pytest.fixture
def sample_sse_dataframe():
    """Retorna um DataFrame de exemplo simulando a Matriz Socioecológica."""
    np.random.seed(42)
    data = {
        "label": [f"Análise {i}" for i in range(1, 11)],
        "municipio_nome": ["Goiânia", "Anápolis", "Rio Verde", "Jataí", "Itumbiara",
                           "Goiânia", "Anápolis", "Rio Verde", "Jataí", "Itumbiara"],
        "municipio_uf": ["GO"] * 10,
        "ano": [2020] * 5 + [2021] * 5,
        "pct_Floresta": [70.0, 65.0, 10.0, 15.0, 12.0, 68.0, 63.0, 11.0, 14.0, 10.0],
        "pct_Pastagem": [20.0, 25.0, 80.0, 75.0, 78.0, 22.0, 27.0, 79.0, 76.0, 80.0],
        "SHDI": [0.8, 0.75, 0.3, 0.35, 0.32, 0.81, 0.76, 0.31, 0.34, 0.30],
        "populacao_estimada_ibge": [1500000, 390000, 240000, 100000, 105000,
                                    1530000, 395000, 243000, 102000, 106000],
    }
    return pd.DataFrame(data)


def test_prepare_clustering_data_basic(sample_sse_dataframe):
    feature_cols = ["pct_Floresta", "pct_Pastagem", "SHDI"]
    cleaned_df, X_scaled, scaler = clustering.prepare_clustering_data(
        sample_sse_dataframe, feature_cols
    )

    assert X_scaled.shape == (10, 3)
    assert scaler is not None
    # Testar se a média padronizada é próxima de 0 e desvio padrão 1
    assert np.allclose(X_scaled.mean(axis=0), 0.0, atol=1e-5)
    assert np.allclose(X_scaled.std(axis=0), 1.0, atol=1e-5)


def test_prepare_clustering_data_empty():
    empty_df = pd.DataFrame()
    cleaned_df, X_scaled, scaler = clustering.prepare_clustering_data(empty_df, ["a", "b"])
    assert X_scaled.shape == (0, 0)
    assert scaler is None


def test_run_kmeans_clusters(sample_sse_dataframe):
    feature_cols = ["pct_Floresta", "pct_Pastagem", "SHDI"]
    res = clustering.run_kmeans(sample_sse_dataframe, feature_cols, k=2, random_state=42)

    assert "cluster_kmeans" in res["df"].columns
    assert res["k"] == 2
    assert res["inertia"] >= 0
    assert res["silhouette"] is not None
    assert 0 <= res["silhouette"] <= 1.0
    assert not res["pca_df"].empty
    assert "pca_1" in res["pca_df"].columns
    assert "pca_2" in res["pca_df"].columns
    assert len(res["cluster_profiles"]) == 2


def test_run_kmeans_k_greater_than_samples(sample_sse_dataframe):
    feature_cols = ["pct_Floresta", "pct_Pastagem"]
    res = clustering.run_kmeans(sample_sse_dataframe.head(3), feature_cols, k=5)
    assert res["k"] == 3  # Ajustado automaticamente para o número máximo de amostras


def test_compute_elbow_curve(sample_sse_dataframe):
    feature_cols = ["pct_Floresta", "pct_Pastagem", "SHDI"]
    elbow_df = clustering.compute_elbow_curve(sample_sse_dataframe, feature_cols, max_k=5)

    assert not elbow_df.empty
    assert list(elbow_df.columns) == ["k", "inertia", "silhouette"]
    assert len(elbow_df) == 4  # k de 2 a 5


def test_run_dbscan(sample_sse_dataframe):
    feature_cols = ["pct_Floresta", "pct_Pastagem", "SHDI"]
    res = clustering.run_dbscan(sample_sse_dataframe, feature_cols, eps=0.8, min_samples=2)

    assert "cluster_dbscan" in res["df"].columns
    assert res["n_clusters"] >= 1
    assert not res["pca_df"].empty
    assert "pca_1" in res["pca_df"].columns
    assert "pca_2" in res["pca_df"].columns
