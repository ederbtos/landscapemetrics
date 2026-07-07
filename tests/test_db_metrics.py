"""Testes do cache de métricas já calculadas (db.metric_results) — ver
docstring de db.py, seção 'Cache de métricas já calculadas'."""
import pandas as pd
import pytest


def _class_metrics_df(metrics=("total_area", "number_of_patches")):
    return pd.DataFrame(
        {m: [1.5, 2.5] for m in metrics},
        index=["Floresta", "Pastagem"],
    )


def test_get_metric_result_returns_none_when_never_saved(temp_db):
    assert temp_db.get_metric_result("user@example.com", "fp1", ["total_area"]) is None


def test_save_and_get_metric_result_roundtrip(temp_db):
    df = _class_metrics_df()
    landscape = {"shannon_diversity_index": 0.42}
    temp_db.save_metric_result(
        "user@example.com", "fp1", "arquivo.tif", "Meu raster (GeoTIFF)",
        None, None, df, landscape,
    )
    result = temp_db.get_metric_result("user@example.com", "fp1", ["total_area", "number_of_patches"])
    assert result is not None
    pd.testing.assert_frame_equal(result["class_metrics_df_sub"], df, check_dtype=False)
    assert result["landscape_metrics"] == landscape


def test_save_metric_result_upsert_replaces_previous(temp_db):
    df_old = _class_metrics_df()
    df_new = _class_metrics_df()
    df_new["total_area"] = [9.9, 9.9]
    temp_db.save_metric_result(
        "user@example.com", "fp1", "old.tif", "Meu raster (GeoTIFF)", None, None, df_old, {},
    )
    temp_db.save_metric_result(
        "user@example.com", "fp1", "new.tif", "Meu raster (GeoTIFF)", None, None, df_new, {},
    )
    result = temp_db.get_metric_result("user@example.com", "fp1", ["total_area"])
    assert result["class_metrics_df_sub"]["total_area"].tolist() == [9.9, 9.9]


def test_get_metric_result_misses_when_a_required_metric_is_missing(temp_db):
    df = _class_metrics_df(metrics=("total_area",))
    temp_db.save_metric_result(
        "user@example.com", "fp1", "arquivo.tif", "Meu raster (GeoTIFF)", None, None, df, {},
    )
    # 'number_of_patches' não estava presente quando o resultado foi salvo —
    # simula uma métrica nova adicionada depois: deve ser tratado como miss.
    assert temp_db.get_metric_result(
        "user@example.com", "fp1", ["total_area", "number_of_patches"]
    ) is None


def test_metric_results_are_scoped_per_user(temp_db):
    df = _class_metrics_df()
    temp_db.save_metric_result(
        "user1@example.com", "fp-shared", "arquivo.tif", "Meu raster (GeoTIFF)", None, None, df, {},
    )
    assert temp_db.get_metric_result("user2@example.com", "fp-shared", ["total_area"]) is None
    assert temp_db.get_metric_result("user1@example.com", "fp-shared", ["total_area"]) is not None


def test_list_metric_results_scoped_per_user_and_ordered_recent_first(temp_db):
    df = _class_metrics_df()
    temp_db.save_metric_result("user1@example.com", "fp1", "a.tif", "Meu raster (GeoTIFF)", None, None, df, {})
    temp_db.save_metric_result("user1@example.com", "fp2", "b.tif", "Meu raster (GeoTIFF)", None, None, df, {})
    temp_db.save_metric_result("user2@example.com", "fp3", "c.tif", "Meu raster (GeoTIFF)", None, None, df, {})

    results = temp_db.list_metric_results("user1@example.com")
    assert [r["label"] for r in results] == ["b.tif", "a.tif"]
    assert "class_metrics_json" not in results[0]


def test_list_metric_results_full_includes_json_blobs(temp_db):
    df = _class_metrics_df()
    temp_db.save_metric_result("user@example.com", "fp1", "a.tif", "Meu raster (GeoTIFF)", None, None, df, {})
    results = temp_db.list_metric_results("user@example.com", full=True)
    assert "class_metrics_json" in results[0]


def test_delete_metric_result_removes_only_that_row(temp_db):
    df = _class_metrics_df()
    temp_db.save_metric_result("user@example.com", "fp1", "a.tif", "Meu raster (GeoTIFF)", None, None, df, {})
    temp_db.save_metric_result("user@example.com", "fp2", "b.tif", "Meu raster (GeoTIFF)", None, None, df, {})
    temp_db.delete_metric_result("user@example.com", "fp1")
    remaining = temp_db.list_metric_results("user@example.com")
    assert [r["fingerprint"] for r in remaining] == ["fp2"]


def test_save_metric_result_stores_point_lonlat_and_buffer(temp_db):
    df = _class_metrics_df()
    temp_db.save_metric_result(
        "user@example.com", "fp1", "MapBiomas", "MapBiomas (Google Earth Engine)",
        (-47.9292, -15.7801), 5000, df, {},
    )
    result = temp_db.list_metric_results("user@example.com")[0]
    assert result["point_lon"] == pytest.approx(-47.9292)
    assert result["point_lat"] == pytest.approx(-15.7801)
    assert result["buffer_dist"] == 5000
