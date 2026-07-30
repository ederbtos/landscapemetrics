"""
Módulo de Agrupamento Multivariado (Clustering)
-----------------------------------------------
Fornece funções para execução de K-Means e DBSCAN, cálculo de curvas de
validação (Elbow Method / Silhouette Score), redução de dimensionalidade (PCA)
e perfilamento de clusters para a Matriz Socioecológica (SSE).
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN, KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)


def prepare_clustering_data(
    df: pd.DataFrame, feature_cols: List[str]
) -> Tuple[pd.DataFrame, np.ndarray, Optional[StandardScaler]]:
    """Prepara e padroniza os dados para algoritmos de clustering.

    - Filtra as colunas numéricas selecionadas.
    - Trata valores ausentes (preenchendo com a mediana ou removendo linhas vazias).
    - Aplica StandardScaler (média=0, variância=1).
    """
    if df.empty or not feature_cols:
        return df.copy(), np.empty((0, 0)), None

    sub_df = df.copy()
    valid_cols = [c for c in feature_cols if c in sub_df.columns]
    if not valid_cols:
        return sub_df, np.empty((len(sub_df), 0)), None

    # Preenche NaNs com a mediana de cada coluna (ou 0 se toda a coluna for NaN)
    for col in valid_cols:
        sub_df[col] = pd.to_numeric(sub_df[col], errors="coerce")
        median_val = sub_df[col].median()
        if pd.isna(median_val):
            median_val = 0.0
        sub_df[col] = sub_df[col].fillna(median_val)

    X = sub_df[valid_cols].values
    if X.shape[0] == 0:
        return sub_df, np.empty((0, len(valid_cols))), None

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    return sub_df, X_scaled, scaler


def run_kmeans(
    df: pd.DataFrame,
    feature_cols: List[str],
    k: int = 3,
    random_state: int = 42,
) -> Dict[str, Any]:
    """Executa o algoritmo K-Means nos dados fornecidos.

    Retorna um dicionário com:
    - "df": DataFrame com a coluna "cluster_kmeans"
    - "silhouette": float ou None
    - "inertia": float
    - "pca_df": DataFrame com eixos pca_1, pca_2 e metadados para gráfico
    - "cluster_profiles": DataFrame com a média das variáveis por cluster
    - "k": int
    """
    cleaned_df, X_scaled, _ = prepare_clustering_data(df, feature_cols)
    n_samples = len(cleaned_df)

    if n_samples == 0 or X_scaled.size == 0:
        result_df = df.copy()
        result_df["cluster_kmeans"] = "Sem dados"
        return {
            "df": result_df,
            "silhouette": None,
            "inertia": 0.0,
            "pca_df": pd.DataFrame(),
            "cluster_profiles": pd.DataFrame(),
            "k": k,
        }

    # Ajusta K se houver menos amostras que clusters solicitados
    effective_k = max(1, min(k, n_samples))

    kmeans = KMeans(n_clusters=effective_k, random_state=random_state, n_init=10)
    labels = kmeans.fit_predict(X_scaled)

    # Rótulos amigáveis: Cluster 1, Cluster 2, ...
    cluster_names = [f"Cluster {lbl + 1}" for lbl in labels]
    cleaned_df["cluster_kmeans"] = cluster_names

    # Cálculo do Silhouette Score (exige pelo menos 2 amostras e k > 1 e k < n_samples)
    sil_score = None
    if 1 < effective_k < n_samples:
        try:
            sil_score = float(silhouette_score(X_scaled, labels))
        except Exception as err:
            logger.warning(f"Não foi possível calcular Silhouette Score: {err}")

    # Redução de dimensionalidade via PCA (2D)
    pca_df = _build_pca_df(X_scaled, cleaned_df, "cluster_kmeans")

    # Perfil dos clusters (médias originais das variáveis)
    valid_cols = [c for c in feature_cols if c in cleaned_df.columns]
    profiles = (
        cleaned_df.groupby("cluster_kmeans")[valid_cols]
        .mean()
        .round(2)
    )

    return {
        "df": cleaned_df,
        "silhouette": sil_score,
        "inertia": float(kmeans.inertia_),
        "pca_df": pca_df,
        "cluster_profiles": profiles,
        "k": effective_k,
    }


def compute_elbow_curve(
    df: pd.DataFrame, feature_cols: List[str], max_k: int = 10
) -> pd.DataFrame:
    """Calcula a inércia e Silhouette Score para K variando de 2 a max_k."""
    cleaned_df, X_scaled, _ = prepare_clustering_data(df, feature_cols)
    n_samples = len(cleaned_df)

    if n_samples < 2 or X_scaled.size == 0:
        return pd.DataFrame(columns=["k", "inertia", "silhouette"])

    limit_k = min(max_k, n_samples - 1)
    rows = []

    for k_val in range(2, limit_k + 1):
        kmeans = KMeans(n_clusters=k_val, random_state=42, n_init=10)
        labels = kmeans.fit_predict(X_scaled)
        sil = None
        try:
            sil = float(silhouette_score(X_scaled, labels))
        except Exception:
            pass

        rows.append({
            "k": k_val,
            "inertia": float(kmeans.inertia_),
            "silhouette": sil,
        })

    return pd.DataFrame(rows)


def run_dbscan(
    df: pd.DataFrame,
    feature_cols: List[str],
    eps: float = 0.5,
    min_samples: int = 2,
) -> Dict[str, Any]:
    """Executa o algoritmo DBSCAN nos dados fornecidos.

    Retorna um dicionário com:
    - "df": DataFrame com a coluna "cluster_dbscan"
    - "n_clusters": int (quantidade de clusters reais encontrados)
    - "n_noise": int (quantidade de pontos classificados como ruído/outliers)
    - "pca_df": DataFrame com eixos pca_1, pca_2 e metadados para gráfico
    - "cluster_profiles": DataFrame com a média das variáveis por cluster
    """
    cleaned_df, X_scaled, _ = prepare_clustering_data(df, feature_cols)
    n_samples = len(cleaned_df)

    if n_samples == 0 or X_scaled.size == 0:
        result_df = df.copy()
        result_df["cluster_dbscan"] = "Sem dados"
        return {
            "df": result_df,
            "n_clusters": 0,
            "n_noise": 0,
            "pca_df": pd.DataFrame(),
            "cluster_profiles": pd.DataFrame(),
        }

    dbscan = DBSCAN(eps=eps, min_samples=min_samples)
    labels = dbscan.fit_predict(X_scaled)

    # Converte rótulos: -1 -> "Outlier (Ruído)", 0 -> "Cluster 1", 1 -> "Cluster 2"
    cluster_names = []
    for lbl in labels:
        if lbl == -1:
            cluster_names.append("Outlier (Ruído)")
        else:
            cluster_names.append(f"Cluster {lbl + 1}")

    cleaned_df["cluster_dbscan"] = cluster_names

    unique_labels = set(labels)
    n_noise = list(labels).count(-1)
    n_clusters = len(unique_labels - {-1})

    # Redução de dimensionalidade via PCA (2D)
    pca_df = _build_pca_df(X_scaled, cleaned_df, "cluster_dbscan")

    # Perfil dos clusters
    valid_cols = [c for c in feature_cols if c in cleaned_df.columns]
    profiles = (
        cleaned_df.groupby("cluster_dbscan")[valid_cols]
        .mean()
        .round(2)
    )

    return {
        "df": cleaned_df,
        "n_clusters": n_clusters,
        "n_noise": n_noise,
        "pca_df": pca_df,
        "cluster_profiles": profiles,
    }


def _build_pca_df(
    X_scaled: np.ndarray, cleaned_df: pd.DataFrame, cluster_col: str
) -> pd.DataFrame:
    """Projeta os dados padronizados em 2 componentes principais (PCA) para visualização."""
    if X_scaled.size == 0 or X_scaled.shape[0] == 0:
        return pd.DataFrame()

    n_samples, n_features = X_scaled.shape
    n_components = min(2, n_samples, n_features)

    if n_components < 1:
        return pd.DataFrame()

    pca = PCA(n_components=n_components, random_state=42)
    components = pca.fit_transform(X_scaled)

    pca_df = pd.DataFrame()
    pca_df["pca_1"] = components[:, 0]
    if n_components >= 2:
        pca_df["pca_2"] = components[:, 1]
    else:
        pca_df["pca_2"] = 0.0

    pca_df[cluster_col] = cleaned_df[cluster_col].values

    # Adiciona colunas de identificação se existirem no DataFrame original
    for meta_col in ["label", "municipio_nome", "municipio_uf", "ano"]:
        if meta_col in cleaned_df.columns:
            pca_df[meta_col] = cleaned_df[meta_col].values
        else:
            pca_df[meta_col] = ""

    return pca_df
