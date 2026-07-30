"""
Módulo de Aprendizado Supervisionado & Validação Cruzada Espacial (Spatial K-Fold)
----------------------------------------------------------------------------------
Fornece treinamento e avaliação de modelos de Machine Learning (Random Forest, XGBoost e LightGBM)
com validação cruzada espacial para evitar autocorrelação espacial, reportando AUC-ROC,
F1-Score, Matriz de Confusão e Importância de Variáveis por Permutação (Permutation Feature Importance).
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.cluster import KMeans
from sklearn.model_selection import GroupKFold
from sklearn.metrics import confusion_matrix, f1_score, roc_auc_score
from sklearn.inspection import permutation_importance
from sklearn.preprocessing import StandardScaler, LabelEncoder

logger = logging.getLogger(__name__)


def prepare_supervised_data(
    df: pd.DataFrame, feature_cols: List[str], target_col: str
) -> Tuple[np.ndarray, np.ndarray, List[str], Optional[StandardScaler], pd.DataFrame]:
    """Prepara os dados numéricos de entrada e codifica a variável alvo (target)."""
    if df.empty or not feature_cols or target_col not in df.columns:
        return np.empty((0, 0)), np.empty(0), [], None, pd.DataFrame()

    sub_df = df.copy()
    valid_cols = [c for c in feature_cols if c in sub_df.columns and c != target_col]
    if not valid_cols:
        return np.empty((len(sub_df), 0)), np.empty(0), [], None, pd.DataFrame()

    # Trata NaNs nas features preenchendo com a mediana
    for col in valid_cols:
        sub_df[col] = pd.to_numeric(sub_df[col], errors="coerce")
        med = sub_df[col].median()
        if pd.isna(med):
            med = 0.0
        sub_df[col] = sub_df[col].fillna(med)

    # Limpa NaNs da variável alvo (target)
    sub_df = sub_df.dropna(subset=[target_col])
    if sub_df.empty:
        return np.empty((0, len(valid_cols))), np.empty(0), valid_cols, None, pd.DataFrame()

    # Codifica o alvo para inteiro [0, 1, ...]
    y_raw = sub_df[target_col].values
    if np.issubdtype(y_raw.dtype, np.number):
        # Se for numérico contínuo, converte em binário (acima/abaixo da mediana)
        median_target = np.median(y_raw)
        y = (y_raw > median_target).astype(int)
    else:
        le = LabelEncoder()
        y = le.fit_transform(y_raw.astype(str))

    X = sub_df[valid_cols].values
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    return X_scaled, y, valid_cols, scaler, sub_df


def get_spatial_groups(df: pd.DataFrame, n_splits: int = 5, random_state: int = 42) -> np.ndarray:
    """Cria grupos de blocos espaciais para evitar autocorrelação espacial.

    - Se houver colunas 'point_lat' e 'point_lon', agrupa via KMeans em blocos geográficos.
    - Se houver 'municipio_codigo', agrupa pelos códigos dos municípios.
    - Caso contrário, atribui índices sequenciais para KFold padrão.
    """
    n_samples = len(df)
    if n_samples == 0:
        return np.array([])

    effective_splits = max(2, min(n_splits, n_samples))

    # As colunas point_lat/point_lon existem na matriz SSE mesmo para análises
    # por município (sem ponto) — checar só a presença da coluna, sem checar
    # se os valores existem de verdade, agrupava tudo em (0, 0) via fillna e
    # o KMeans degenerava num único cluster (n_clusters pedido > clusters
    # reais), quebrando o GroupKFold seguinte com "n_splits maior que o
    # número de grupos" para qualquer usuário com análises só por
    # município/raster inteiro (sem ponto+buffer).
    if "point_lat" in df.columns and "point_lon" in df.columns:
        coords_df = df[["point_lat", "point_lon"]]
        if coords_df.notna().all(axis=None) and len(coords_df) >= effective_splits:
            km = KMeans(n_clusters=effective_splits, random_state=random_state, n_init=10)
            return km.fit_predict(coords_df.values)

    if "municipio_codigo" in df.columns and df["municipio_codigo"].notna().any():
        codes = df["municipio_codigo"].astype(str).values
        le = LabelEncoder()
        return le.fit_transform(codes)

    return np.arange(n_samples) % effective_splits


def train_supervised_model(
    df: pd.DataFrame,
    feature_cols: List[str],
    target_col: str,
    model_name: str = "random_forest",
    n_splits: int = 5,
    random_state: int = 42,
) -> Dict[str, Any]:
    """Treina um modelo supervisionado (Random Forest, XGBoost ou LightGBM) com Validação Cruzada Espacial.

    Retorna um dicionário contendo:
    - "model_name": str
    - "auc_roc": float ou None
    - "f1_score": float
    - "confusion_matrix": List[List[int]]
    - "permutation_importance": Dict[str, float]
    - "feature_names": List[str]
    - "n_samples": int
    - "n_splits": int
    """
    X_scaled, y, valid_cols, scaler, clean_df = prepare_supervised_data(df, feature_cols, target_col)
    n_samples = len(y)

    if n_samples < 4 or len(valid_cols) == 0 or len(np.unique(y)) < 2:
        return {
            "model_name": model_name,
            "auc_roc": None,
            "f1_score": 0.0,
            "confusion_matrix": [],
            "permutation_importance": {},
            "feature_names": valid_cols,
            "n_samples": n_samples,
            "n_splits": 0,
            "error": "Dados insuficientes ou apenas 1 classe presente para treinamento supervisionado.",
        }

    # Grupos espaciais para Spatial K-Fold
    groups = get_spatial_groups(clean_df, n_splits=n_splits, random_state=random_state)
    n_unique_groups = len(np.unique(groups))
    effective_splits = max(2, min(n_splits, n_unique_groups, n_samples))

    gkf = GroupKFold(n_splits=effective_splits)

    oof_preds = np.zeros(n_samples, dtype=int)
    oof_probs = np.zeros(n_samples, dtype=float)

    def _instantiate_model(name: str):
        if name == "xgboost":
            try:
                from xgboost import XGBClassifier
                return XGBClassifier(
                    n_estimators=100,
                    random_state=random_state,
                    eval_metric="logloss",
                    verbosity=0,
                )
            except ImportError:
                logger.warning("XGBoost não encontrado, utilizando RandomForest como fallback.")
                return RandomForestClassifier(n_estimators=100, random_state=random_state)
        elif name == "lightgbm":
            try:
                from lightgbm import LGBMClassifier
                return LGBMClassifier(
                    n_estimators=100,
                    random_state=random_state,
                    verbose=-1,
                )
            except ImportError:
                logger.warning("LightGBM não encontrado, utilizando RandomForest como fallback.")
                return RandomForestClassifier(n_estimators=100, random_state=random_state)
        else:
            return RandomForestClassifier(n_estimators=100, random_state=random_state)

    # Validação Cruzada Espacial (Spatial K-Fold)
    for train_idx, val_idx in gkf.split(X_scaled, y, groups=groups):
        X_train, y_train = X_scaled[train_idx], y[train_idx]
        X_val = X_scaled[val_idx]

        if len(np.unique(y_train)) < 2:
            continue

        clf = _instantiate_model(model_name)
        clf.fit(X_train, y_train)

        oof_preds[val_idx] = clf.predict(X_val)
        if hasattr(clf, "predict_proba"):
            probs = clf.predict_proba(X_val)
            oof_probs[val_idx] = probs[:, 1] if probs.shape[1] > 1 else probs[:, 0]

    # Modelo final treinado no conjunto completo para Permutation Importance
    final_model = _instantiate_model(model_name)
    final_model.fit(X_scaled, y)

    # Cálculo da Importância de Variáveis por Permutação
    perm_imp = permutation_importance(
        final_model, X_scaled, y, n_repeats=10, random_state=random_state
    )
    importances_dict = {}
    for idx, col in enumerate(valid_cols):
        importances_dict[col] = float(np.round(perm_imp.importances_mean[idx], 4))

    # Ordena importância em ordem decrescente
    importances_dict = dict(sorted(importances_dict.items(), key=lambda x: x[1], reverse=True))

    # Cálculo das métricas de avaliação
    f1 = float(f1_score(y, oof_preds, average="weighted"))
    cm = confusion_matrix(y, oof_preds).tolist()

    auc = None
    if len(np.unique(y)) == 2:
        try:
            auc = float(roc_auc_score(y, oof_probs))
        except Exception:
            auc = None

    return {
        "model_name": model_name,
        "auc_roc": auc,
        "f1_score": f1,
        "confusion_matrix": cm,
        "permutation_importance": importances_dict,
        "feature_names": valid_cols,
        "n_samples": n_samples,
        "n_splits": effective_splits,
    }
