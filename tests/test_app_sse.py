"""
Testes da matriz socioecológica (SSE) — _build_sse_matrix/_render_sse_matrix_section
(app.py), que agrega o histórico salvo em db.metric_results numa matriz
multivariada (uma linha por análise). Ver "Matriz socioecológica (SSE)" no
ROADMAP.md.
"""
import pandas as pd
import pytest

import app


def _class_metrics_df(class_props: dict) -> pd.DataFrame:
    return pd.DataFrame(
        {"proportion_of_landscape": list(class_props.values())},
        index=list(class_props.keys()),
    )


def test_build_sse_matrix_empty_when_no_history(temp_db):
    assert app._build_sse_matrix("user@example.com").empty


def test_build_sse_matrix_one_row_per_saved_analysis(temp_db):
    df = _class_metrics_df({"Floresta": 60.0, "Pastagem": 40.0})
    temp_db.save_metric_result(
        "user@example.com", "fp1", "Goiânia/GO", "MapBiomas (Google Earth Engine)",
        None, None, df, {"shannon_diversity_index": 0.9},
        municipio_codigo="5208707", municipio_nome="Goiânia", municipio_uf="GO", ano=2020,
    )

    matrix = app._build_sse_matrix("user@example.com")

    assert len(matrix) == 1
    row = matrix.iloc[0]
    assert row["pct_Floresta"] == pytest.approx(60.0)
    assert row["pct_Pastagem"] == pytest.approx(40.0)
    assert row["municipio_nome"] == "Goiânia"
    assert row["municipio_codigo"] == "5208707"
    assert row["ano"] == 2020
    assert row["SHDI"] == pytest.approx(0.9)  # LANDSCAPE_METRICS_INFO: shannon_diversity_index -> "SHDI"


def test_build_sse_matrix_fills_missing_class_columns_with_zero(temp_db):
    df1 = _class_metrics_df({"Floresta": 100.0})
    df2 = _class_metrics_df({"Pastagem": 100.0})
    temp_db.save_metric_result(
        "user@example.com", "fp1", "a", "MapBiomas (Google Earth Engine)", None, None, df1, {},
    )
    temp_db.save_metric_result(
        "user@example.com", "fp2", "b", "MapBiomas (Google Earth Engine)", None, None, df2, {},
    )

    matrix = app._build_sse_matrix("user@example.com")

    assert len(matrix) == 2
    assert "pct_Floresta" in matrix.columns and "pct_Pastagem" in matrix.columns
    assert set(matrix["pct_Floresta"]) == {0.0, 100.0}
    assert set(matrix["pct_Pastagem"]) == {0.0, 100.0}
    assert not matrix["pct_Floresta"].isna().any()


def test_build_sse_matrix_scoped_per_user(temp_db):
    df = _class_metrics_df({"Floresta": 100.0})
    temp_db.save_metric_result(
        "user1@example.com", "fp1", "a", "MapBiomas (Google Earth Engine)", None, None, df, {},
    )

    assert app._build_sse_matrix("user1@example.com").shape[0] == 1
    assert app._build_sse_matrix("user2@example.com").empty


def test_render_sse_matrix_section_does_not_raise_without_history(temp_db):
    app._render_sse_matrix_section("user@example.com")  # só garante que não levanta exceção


def test_render_sse_matrix_section_does_not_raise_with_history(temp_db):
    df = _class_metrics_df({"Floresta": 100.0})
    temp_db.save_metric_result(
        "user@example.com", "fp1", "a", "MapBiomas (Google Earth Engine)", None, None, df, {},
    )
    app._render_sse_matrix_section("user@example.com")  # só garante que não levanta exceção
